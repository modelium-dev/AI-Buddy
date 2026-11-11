"""Главное правило продукта: тексты чатов технически недоступны наставнику, лиду и HR (глава 12 ТЗ)."""
from __future__ import annotations

import pytest

from app.authz import Resource, decide
from app.security import Subject

PERSONAL_GET = ["/api/chats", "/api/contacts", "/api/journal", "/api/practice", "/api/privacy", "/api/actions", "/api/home",
                "/api/checklist", "/api/tasks"]


@pytest.mark.parametrize("role_user", ["boris", "maria"])
@pytest.mark.parametrize("url", PERSONAL_GET)
async def test_mentor_and_lead_get_403_on_personal_endpoints(api, role_user, url):
    r = await api.get(role_user, url)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("role_user", ["boris", "maria"])
async def test_mentor_cannot_read_messages_and_denial_is_logged(api, role_user):
    chat_id = await api.new_chat("anya")
    await api.ask("Что такое грумминг?", chat_id)
    r = await api.get(role_user, f"/api/chats/{chat_id}/messages")
    assert r.status_code == 403
    assert "грумминг" not in r.text.lower()
    for method, url, body in [("post", f"/api/chats/{chat_id}/messages", {"text": "привет"}), ("patch", f"/api/chats/{chat_id}", {"title": "x"}),
                              ("delete", f"/api/chats/{chat_id}", None), ("post", f"/api/chats/{chat_id}/attachments", None)]:
        if method == "delete":
            resp = await api.delete(role_user, url)
        elif method == "patch":
            resp = await api.patch(role_user, url, body)
        else:
            resp = await api.post(role_user, url, body)
        assert resp.status_code in (403, 422), (url, resp.status_code)
    msgs = (await api.get("anya", f"/api/chats/{chat_id}/messages")).json()["messages"]
    r = await api.post(role_user, f"/api/messages/{msgs[-1]['id']}/feedback", {"helpful": True})
    assert r.status_code == 403
    log = (await api.get("anya", "/api/privacy")).json()["access_log"]
    assert any(entry["decision"] == "deny" and entry["resource"] == "chat_message" for entry in log)


async def test_foreign_chat_returns_404_for_other_intern(api):
    chat_id = await api.new_chat("dima")
    assert (await api.get("anya", f"/api/chats/{chat_id}/messages")).status_code == 404
    assert (await api.patch("anya", f"/api/chats/{chat_id}", {"title": "чужой"})).status_code == 404
    assert (await api.delete("anya", f"/api/chats/{chat_id}")).status_code == 404
    assert (await api.get("anya", "/api/chats/unknown/messages")).status_code == 404
    assert (await api.post("anya", "/api/messages/unknown/feedback", {"helpful": True})).status_code == 404
    assert (await api.post("boris", "/api/messages/unknown/feedback", {"helpful": True})).status_code == 403


async def test_unauthorized_and_bad_login(api):
    r = await api.client.get("/api/me")
    assert r.status_code == 401
    r = await api.client.get("/api/me", headers={"Authorization": "Bearer broken"})
    assert r.status_code == 401
    r = await api.client.post("/api/auth/login", json={"user_id": "igor"})
    assert r.status_code == 404
    r = await api.client.post("/api/auth/login", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


async def test_login_and_me(api):
    users = (await api.client.get("/api/auth/users")).json()
    assert {u["id"] for u in users} == {"anya", "dima", "boris", "maria"}
    me = (await api.get("anya", "/api/me")).json()
    assert me["intern"]["day"] == 12 and me["intern"]["stage"]["id"] == "w24"
    assert "Ваши чаты видите только вы" in me["privacy"]["first_entry_text"]
    assert me["privacy"]["seen_privacy"] is False
    assert (await api.post("anya", "/api/me/privacy-ack")).json()["seen_privacy"] is True
    mentor = (await api.get("boris", "/api/me")).json()
    assert mentor["role"] == "mentor" and "intern" not in mentor


def _s(role: str, uid: str = "u") -> Subject:
    return Subject(id=uid, role=role, team_id="payments", name="x")


@pytest.mark.parametrize("subject,relation,action,resource,allowed", [
    (_s("intern"), "self", "read", Resource("chat_message"), True),
    (_s("mentor"), "mentor_of", "read", Resource("chat_message"), False),
    (_s("lead"), "manager_of", "read", Resource("contact"), False),
    (_s("mentor"), "mentor_of", "read", Resource("journal_entry", extra={"shared": True}), True),
    (_s("mentor"), "mentor_of", "read", Resource("journal_entry"), False),
    (_s("intern"), "self", "write", Resource("journal_entry"), True),
    (_s("mentor"), "mentor_of", "read", Resource("topic", extra={"share_topics": False}), False),
    (_s("mentor"), "mentor_of", "read", Resource("topic", extra={"share_topics": True}), True),
    (_s("intern"), "self", "read", Resource("topic"), True),
    (_s("mentor"), "mentor_of", "read", Resource("checklist_progress"), True),
    (_s("mentor"), "none", "read", Resource("checklist_progress"), False),
    (_s("lead"), "none", "read", Resource("task", team_id="payments"), True),
    (_s("lead"), "none", "read", Resource("task", team_id="other"), False),
    (_s("mentor"), "mentor_of", "create", Resource("task"), True),
    (_s("mentor"), "mentor_of", "write", Resource("absence"), False),
    (_s("intern"), "self", "write", Resource("checklist_progress"), True),
    (_s("intern"), "self", "write", Resource("task"), False),
    (_s("intern"), "self", "read", Resource("document", access_level="lead"), False),
    (_s("lead"), "none", "read", Resource("document", access_level="lead"), True),
    (_s("intern"), "self", "read", Resource("document", access_level="public"), True),
    (_s("intern"), "self", "read", Resource("document", access_level="team", team_id="other"), False),
    (_s("intern"), "self", "request_access", Resource("document", space="global", access_level="public"), False),
    (_s("mentor"), "none", "read", Resource("mentor_page"), True),
    (_s("intern"), "none", "read", Resource("mentor_page"), False),
    (_s("intern"), "self", "read", Resource("unknown"), False),
])
def test_authorize_rules_table(subject, relation, action, resource, allowed):
    assert bool(decide(subject, relation, action, resource)) is allowed


async def test_privacy_screen_and_settings(api):
    data = (await api.get("anya", "/api/privacy")).json()
    rows = {r["data"]: r for r in data["matrix"]}
    assert rows["Чаты и вопросы"]["mentor"] == "no" and rows["Чаты и вопросы"]["lead"] == "no"
    assert rows["Прогресс чек-листа"]["mentor"] == "Да, по умолчанию"
    assert data["settings"]["share_topics"] is False and data["checklist_visible_to_mentor_by_default"] is True
    assert data["ai_provider"]["mode"] == "fake"
    interns = (await api.get("boris", "/api/mentor/interns")).json()["interns"]
    assert "topic" not in interns[0]
    assert (await api.put("anya", "/api/privacy/settings", {"share_topics": True})).json()["share_topics"] is True
    interns = (await api.get("boris", "/api/mentor/interns")).json()["interns"]
    anya = next(i for i in interns if i["intern"]["id"] == "anya")
    assert anya["topic"] == "Платёжный модуль"
    assert (await api.get("anya", "/api/privacy")).json()["matrix"][-1]["mentor"] == "yes"


async def test_delete_all_chats_keeps_journal_and_contacts(api):
    before_journal = len((await api.get("anya", "/api/journal")).json()["entries"])
    before_contacts = len((await api.get("anya", "/api/contacts")).json())
    r = await api.delete("anya", "/api/privacy/chats")
    assert r.json()["deleted"] >= 5
    assert (await api.get("anya", "/api/chats")).json()["history"] == []
    entries = (await api.get("anya", "/api/journal")).json()["entries"]
    assert len(entries) == before_journal and all(e["source_chat_id"] is None for e in entries)
    assert any(e["chat_deleted"] for e in entries)
    assert len((await api.get("anya", "/api/contacts")).json()) == before_contacts
