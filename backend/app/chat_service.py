import asyncio
from time import perf_counter_ns

from app.config import Settings
from app.database import Database
from app.gateway import InferenceGateway
from app.models import ChatRequest, ChatResponse, HistoryResponse, ReplyMetadata
from app.session_locks import SessionLocks


class ChatService:
    def __init__(self, settings: Settings, database: Database, gateway: InferenceGateway) -> None:
        self.settings = settings
        self.database = database
        self.gateway = gateway
        self.locks = SessionLocks()

    async def chat(self, body: ChatRequest, failures: dict[str, int]) -> ChatResponse:
        started = perf_counter_ns()
        async with self.locks.hold(body.session_id):
            saved_prompt, history = await asyncio.to_thread(
                self.database.load_session, body.session_id
            )
            effective_prompt = body.system_prompt
            if effective_prompt is None:
                effective_prompt = (
                    saved_prompt
                    if saved_prompt is not None
                    else self.settings.default_system_prompt
                )
            messages = [
                {"role": "system", "content": effective_prompt},
                *[{"role": message.role, "content": message.content} for message in history],
                {"role": "user", "content": body.message},
            ]
            result = await self.gateway.infer(messages, failures)
            response = ChatResponse(
                session_id=body.session_id,
                reply=result.reply,
                metadata=ReplyMetadata(
                    resolution_source=result.resolution_source,
                    model=result.model,
                    latency_ms=(perf_counter_ns() - started) // 1_000_000,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    key_id=result.key_id,
                    fallback_attempts=result.fallback_attempts,
                ),
            )
            write_task = asyncio.create_task(
                asyncio.to_thread(
                    self.database.save_turn,
                    body.session_id,
                    effective_prompt,
                    body.message,
                    response.reply,
                    response.metadata,
                )
            )
            cancelled = False
            while not write_task.done():
                try:
                    await asyncio.shield(write_task)
                except asyncio.CancelledError:
                    # Cancellation cannot stop a database thread; retain the lock until commit.
                    cancelled = True
            write_task.result()
            if cancelled:
                raise asyncio.CancelledError
            return response

    async def history(self, session_id: str) -> HistoryResponse | None:
        async with self.locks.hold(session_id):
            saved_prompt, history = await asyncio.to_thread(self.database.load_session, session_id)
        if saved_prompt is None:
            return None
        return HistoryResponse(session_id=session_id, messages=history)
