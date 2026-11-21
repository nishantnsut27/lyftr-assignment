import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class SessionLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class SessionLocks:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionLock] = {}

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        # Count waiters too: deleting a lock while it has waiters could split a session's queue.
        entry = self._sessions.setdefault(session_id, SessionLock())
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0:
                del self._sessions[session_id]
