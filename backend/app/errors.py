import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class ProvidersUnavailable(Exception):
    pass


class InferenceFailed(Exception):
    pass


class InvalidFailureSimulation(Exception):
    pass


class JsonErrorsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception:
            # Starlette rethrows exception-handler errors to Uvicorn, which logs raw tracebacks.
            logger.error("request_failed")
            if not response_started:
                response = JSONResponse(
                    status_code=500, content={"detail": "internal server error"}
                )
                await response(scope, receive, send)
