from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("MCP_URL", "inprocess")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("ATTACHMENTS_DIR", tempfile.mkdtemp(prefix="buddy-att-"))

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import database  # noqa: E402
from app.kv import reset_kv  # noqa: E402
from app.llm import get_embedder, set_embedder, set_llm  # noqa: E402
from app.main import app  # noqa: E402
from app.mcp_client import get_mcp, set_mcp  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.seed import seed_all  # noqa: E402

TEST_DB = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


class Api:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    async def h(self, user: str) -> dict:
        if user not in self.tokens:
            r = await self.client.post("/api/auth/login", json={"user_id": user})
            assert r.status_code == 200, r.text
            self.tokens[user] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    async def get(self, user: str, url: str, **kw):
        return await self.client.get(url, headers=await self.h(user), **kw)

    async def post(self, user: str, url: str, json=None, **kw):
        headers = {**(await self.h(user)), **kw.pop("headers", {})}
        return await self.client.post(url, json=json, headers=headers, **kw)

    async def patch(self, user: str, url: str, json=None):
        return await self.client.patch(url, json=json, headers=await self.h(user))

    async def put(self, user: str, url: str, json=None):
        return await self.client.put(url, json=json, headers=await self.h(user))

    async def delete(self, user: str, url: str):
        return await self.client.delete(url, headers=await self.h(user))

    async def new_chat(self, user: str = "anya", task_id: str | None = None) -> str:
        r = await self.post(user, "/api/chats", {"task_id": task_id} if task_id else {})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def ask(self, text: str, chat_id: str | None = None, user: str = "anya", mode: str = "guide", **kw) -> list[tuple[str, dict]]:
        chat_id = chat_id or await self.new_chat(user)
        r = await self.post(user, f"/api/chats/{chat_id}/messages", {"text": text, "mode": mode, **kw.pop("body", {})}, **kw)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")
        return parse_sse(r.text)

    async def task_id(self, external_id: str, user: str = "anya") -> str:
        r = await self.get(user, "/api/tasks")
        return next(t["id"] for t in r.json() if t["external_id"] == external_id)


def first(events: list[tuple[str, dict]], name: str) -> dict | None:
    return next((d for n, d in events if n == name), None)


def names(events: list[tuple[str, dict]]) -> list[str]:
    return [n for n, _ in events]


def text_of(events: list[tuple[str, dict]]) -> str:
    return "".join(d["text"] for n, d in events if n == "token")


@pytest.fixture
async def api():
    from mock_corp import state

    state.reset()
    reset_kv(None)
    set_llm(None)
    set_embedder(None)
    set_mcp(None)
    database.init(TEST_DB)
    await database.drop_all()
    await database.create_all()
    async with database.session() as session:
        await seed_all(session, get_mcp(), get_embedder(), get_settings().seed_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Api(client)
    await database.dispose()
