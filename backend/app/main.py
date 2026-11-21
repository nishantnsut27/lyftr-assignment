import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.chat_service import ChatService
from app.config import Settings
from app.cors import JsonCORSMiddleware
from app.database import Database
from app.errors import (
    InferenceFailed,
    InvalidFailureSimulation,
    JsonErrorsMiddleware,
    ProvidersUnavailable,
)
from app.gateway import InferenceGateway, LiteLLMGateway
from app.models import ChatRequest, ChatResponse, HealthResponse, HistoryResponse
from app.simulation import parse_failure_simulation


def create_app(
    settings: Settings | None = None,
    gateway: InferenceGateway | None = None,
    database: Database | None = None,
) -> JsonCORSMiddleware:
    try:
        configuration = settings or Settings()
    except ValidationError:
        raise RuntimeError("Invalid backend configuration; check environment settings") from None

    history_database = database or Database(configuration.database_path)
    inference_gateway = gateway or LiteLLMGateway(configuration)
    service = ChatService(configuration, history_database, inference_gateway)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await asyncio.to_thread(history_database.initialize)
            yield
        finally:
            await asyncio.to_thread(inference_gateway.close)

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    app.state.database = history_database
    app.state.gateway = inference_gateway
    app.add_middleware(JsonErrorsMiddleware)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code, content={"detail": error.detail}, headers=error.headers
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        try:
            await asyncio.to_thread(history_database.check_health)
        except Exception:
            raise HTTPException(status_code=503, detail="database unavailable") from None
        if not await asyncio.to_thread(inference_gateway.check_cache_health):
            raise HTTPException(status_code=503, detail="cache unavailable")
        return HealthResponse(keys_configured=len(configuration.api_keys), cache_enabled=True)

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest, x_simulate_failure: str | None = Header(default=None)
    ) -> ChatResponse:
        try:
            failures = (
                parse_failure_simulation(x_simulate_failure, len(configuration.api_keys))
                if configuration.enable_failure_simulation
                else {}
            )
        except InvalidFailureSimulation:
            raise HTTPException(
                status_code=422, detail="invalid failure simulation header"
            ) from None
        try:
            return await service.chat(body, failures)
        except ProvidersUnavailable:
            raise HTTPException(status_code=503, detail="all providers unavailable") from None
        except InferenceFailed:
            raise HTTPException(status_code=502, detail="could not generate a reply") from None

    @app.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
    async def session_messages(session_id: str) -> HistoryResponse:
        history = await service.history(session_id)
        if history is None:
            raise HTTPException(status_code=404, detail="session not found")
        return history

    # Wrap the entire app so JSON errors and successful responses both carry CORS headers.
    return JsonCORSMiddleware(
        app,
        allow_origins=configuration.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
        allow_credentials=False,
    )
