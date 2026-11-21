import asyncio
import threading
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from app.database import Database
from app.gateway import LiteLLMGateway
from app.main import create_app
from app.session_locks import SessionLocks
from tests.conftest import FakeCompletion


@asynccontextmanager
async def client_for(settings, fake, database=None):
    app = create_app(settings, gateway=LiteLLMGateway(settings, fake), database=database)
    async with app.app.router.lifespan_context(app.app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            yield client


async def test_concurrent_same_session_turns_see_committed_history(settings):
    fake = FakeCompletion(delay=0.03)
    fake.started = asyncio.Event()
    async with client_for(settings, fake) as client:
        first_task = asyncio.create_task(
            client.post("/chat", json={"session_id": "s", "message": "First"})
        )
        await fake.started.wait()
        second_task = asyncio.create_task(
            client.post("/chat", json={"session_id": "s", "message": "Second"})
        )
        first, second = await asyncio.gather(first_task, second_task)
        assert first.status_code == second.status_code == 200
        assert fake.calls[1]["messages"] == [
            {"role": "system", "content": settings.default_system_prompt},
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": first.json()["reply"]},
            {"role": "user", "content": "Second"},
        ]
        history = (await client.get("/sessions/s/messages")).json()["messages"]
        assert [message["content"] for message in history] == [
            "First",
            first.json()["reply"],
            "Second",
            second.json()["reply"],
        ]


async def test_distinct_sessions_can_infer_concurrently(settings):
    class ConcurrentCompletion(FakeCompletion):
        def __init__(self):
            super().__init__(delay=0)
            self.active = 0
            self.overlap = asyncio.Event()

        async def __call__(self, **kwargs):
            self.active += 1
            if self.active == 2:
                self.overlap.set()
            try:
                await asyncio.wait_for(self.overlap.wait(), timeout=3)
                return await super().__call__(**kwargs)
            finally:
                self.active -= 1

    fake = ConcurrentCompletion()
    async with client_for(settings, fake) as client:
        first, second = await asyncio.gather(
            client.post("/chat", json={"session_id": "one", "message": "First"}),
            client.post("/chat", json={"session_id": "two", "message": "Second"}),
        )
        assert first.status_code == second.status_code == 200
        assert fake.overlap.is_set()
        assert all(len(call["messages"]) == 2 for call in fake.calls)


async def test_history_reader_waits_for_same_session_completion(settings):
    fake = FakeCompletion()
    fake.started = asyncio.Event()
    async with client_for(settings, fake) as client:
        sending = asyncio.create_task(
            client.post("/chat", json={"session_id": "s", "message": "Hello"})
        )
        await fake.started.wait()
        history_task = asyncio.create_task(client.get("/sessions/s/messages"))
        await sending
        history = await history_task
        assert history.status_code == 200
        assert [message["role"] for message in history.json()["messages"]] == ["user", "assistant"]


async def test_cancelled_waiter_does_not_split_session_queue():
    locks = SessionLocks()
    async with locks.hold("s"):

        async def wait_for_lock():
            async with locks.hold("s"):
                raise AssertionError("cancelled waiter acquired the lock")

        waiting = asyncio.create_task(wait_for_lock())
        await asyncio.sleep(0)
        waiting.cancel()
        try:
            await waiting
        except asyncio.CancelledError:
            pass
        assert locks._sessions["s"].users == 1
    assert not locks._sessions
    async with locks.hold("s"):
        assert locks._sessions["s"].users == 1
    assert not locks._sessions


async def test_cancellation_during_database_write_keeps_lock_until_commit(settings):
    entered = threading.Event()
    release = threading.Event()

    class PausedDatabase(Database):
        def save_turn(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=5), "test did not release database write"
            return super().save_turn(*args, **kwargs)

    fake = FakeCompletion(delay=0)
    database = PausedDatabase(settings.database_path)
    async with client_for(settings, fake, database) as client:
        first = asyncio.create_task(
            client.post("/chat", json={"session_id": "s", "message": "First"})
        )
        assert await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(
            client.post("/chat", json={"session_id": "s", "message": "Second"})
        )
        await asyncio.sleep(0.02)
        assert len(fake.calls) == 1
        release.set()
        try:
            await first
        except asyncio.CancelledError:
            pass
        response = await second
        assert response.status_code == 200
        assert fake.calls[1]["messages"][1]["content"] == "First"
        assert len((await client.get("/sessions/s/messages")).json()["messages"]) == 4
