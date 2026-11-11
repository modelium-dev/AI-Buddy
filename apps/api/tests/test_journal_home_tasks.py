"""Журнал, знакомства, главная, чек-лист, задачи, наставник, dev-панель и служебные ручки."""
from __future__ import annotations

from conftest import first


async def test_journal_suggest_snapshot_survives_chat_deletion(api):
    chats = (await api.get("anya", "/api/chats")).json()
    config = next(c for c in chats["history"] if c["title"] == "Где лежит конфиг Billing")
    suggestions = (await api.post("anya", "/api/journal/suggest", {"chat_ids": [config["id"]]})).json()
    assert suggestions["items"][0]["text"].startswith("Разобралась")
    stand = next(c for c in chats["history"] if c["title"] == "Доступ к тестовому стенду")
    assert (await api.post("anya", "/api/journal/suggest", {"chat_ids": [stand["id"]]})).json()["empty_text"]
    assert (await api.post("anya", "/api/journal/suggest", {"chat_ids": ["nope"]})).status_code == 404
    created = (await api.post("anya", "/api/journal", {"entries": [{"text": "Разобралась с конфигами", "source_chat_id": config["id"]}]})).json()
    entry = created["entries"][0]
    assert entry["source_label"] == "Из чата «Где лежит конфиг Billing»"
    assert (await api.delete("anya", f"/api/chats/{config['id']}")).status_code == 204
    journal = (await api.get("anya", "/api/journal")).json()
    assert "остаётся в журнале" in journal["note"]
    kept = next(e for e in journal["entries"] if e["id"] == entry["id"])
    assert kept["chat_deleted"] is True and kept["source_label"].startswith("Чат удалён")
    patched = (await api.patch("anya", f"/api/journal/{entry['id']}", {"text": "Новый текст", "include_in_export": False,
                                                                         "shared_with_mentor": True})).json()
    assert patched["text"] == "Новый текст" and patched["include_in_export"] is False
    mentor = (await api.get("boris", "/api/mentor/interns")).json()["interns"]
    assert next(i for i in mentor if i["intern"]["id"] == "anya")["shared_journal"][0]["text"] == "Новый текст"
    draft = (await api.post("anya", "/api/journal/draft", {})).json()
    assert "За это время я:" in draft["text"] and "Новый текст" not in draft["text"]
    draft_selected = (await api.post("anya", "/api/journal/draft", {"entry_ids": [entry["id"]]})).json()
    assert "Новый текст" in draft_selected["text"]
    pdf = await api.post("anya", "/api/journal/export", {"text": draft["text"]})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert (await api.delete("anya", f"/api/journal/{entry['id']}")).status_code == 204
    assert (await api.delete("anya", f"/api/journal/{entry['id']}")).status_code == 404
    assert (await api.post("anya", "/api/journal", {"entries": [{"text": "x", "source_chat_id": "nope"}]})).status_code == 404
    assert (await api.post("dima", "/api/journal/draft", {})).status_code == 404


async def test_journal_suggest_from_new_chat_hint(api):
    chat_id = await api.new_chat()
    await api.ask("Мне нужен доступ к Jira-проекту PAY", chat_id)
    items = (await api.post("anya", "/api/journal/suggest", {"chat_ids": [chat_id]})).json()["items"]
    assert items[0]["text"].startswith("Оформила заявку на доступ к Jira-проекту PAY")


async def test_pdf_fallback_without_font(monkeypatch):
    from app.config import get_settings
    from app.services.journal import render_pdf

    monkeypatch.setattr(get_settings(), "pdf_font_paths", "/nope/font.ttf")
    assert render_pdf("Журнал", "Сделала задачу — «Платёжный модуль»").startswith(b"%PDF")


async def test_contacts_crud_and_search(api):
    contacts = (await api.get("anya", "/api/contacts")).json()
    assert {c["name"] for c in contacts} == {"Борис Н.", "Олег Р."}
    manual = (await api.post("anya", "/api/contacts", {"name": "Петя К.", "role": "Аналитик", "topics": ["метрики"], "note": "сосед по столу"})).json()
    assert manual["person_id"] is None
    assert len((await api.get("anya", "/api/contacts", params={"q": "метрик"})).json()) == 1
    updated = (await api.patch("anya", f"/api/contacts/{manual['id']}", {"note": "любит кофе"})).json()
    assert updated["note"] == "любит кофе"
    assert (await api.post("anya", "/api/contacts", {"role": "без имени"})).status_code == 422
    assert (await api.post("anya", "/api/contacts", {"person_id": "ghost"})).status_code == 404
    assert (await api.post("anya", "/api/contacts", {"name": "X", "source_chat_id": "nope"})).status_code == 404
    assert (await api.patch("dima", f"/api/contacts/{manual['id']}", {"note": "x"})).status_code == 404
    assert (await api.delete("anya", f"/api/contacts/{manual['id']}")).status_code == 204
    chat_id = await api.new_chat()
    sveta = (await api.post("anya", "/api/contacts", {"person_id": "sveta", "source_chat_id": chat_id})).json()
    assert sveta["source_chat_title"] == "Новый чат" and sveta["role"] == "HR BP"


async def test_home_checklist_and_notifications(api):
    home = (await api.get("anya", "/api/home")).json()
    assert home["stage"]["label"] == "Недели 2–4" and home["day"] == 12 and home["total_days"] == 180
    assert home["normalization_text"].endswith("Это нормально.")
    assert home["digest"]["unresolved"] is True and "Не решено" in home["digest"]["text"]
    assert home["next_step"]["step_id"] == "w24-access" and home["suggestions"][0] == "Кто отвечает за сервис платежей?"
    assert [t["title"] for t in home["tasks_today"]] == ["Платёжный модуль"]
    assert [s["state"] for s in home["stages"]][:4] == ["done", "done", "done", "current"]
    assert len(home["notifications"]) == 1
    checklist = (await api.get("anya", "/api/checklist")).json()
    current = next(s for s in checklist["stages"] if s["current"])
    assert current["id"] == "w24" and current["done"] == 1
    assert (await api.patch("anya", "/api/checklist/w24-access", {"status": "hidden"})).json()["status"] == "hidden"
    assert (await api.get("anya", "/api/home")).json()["next_step"]["step_id"] == "w24-stand"
    assert (await api.patch("anya", "/api/checklist/nope", {"status": "done"})).status_code == 404
    assert (await api.patch("anya", "/api/checklist/w24-stand", {"status": "wrong"})).status_code == 422
    notes = (await api.get("anya", "/api/notifications")).json()
    assert notes["unread"] == 1
    read = (await api.post("anya", f"/api/notifications/{notes['items'][0]['id']}/read")).json()
    assert read["read"] is True
    assert (await api.post("dima", f"/api/notifications/{notes['items'][0]['id']}/read")).status_code == 404
    assert (await api.post("anya", "/api/notifications/read-all")).json()["unread"] == 0
    dima = (await api.get("dima", "/api/home")).json()
    assert dima["stage"]["id"] == "w1" and dima["digest"]["chat_id"] is None


async def test_tasks_folders_lock_and_mentor_creates_task(api):
    tasks = (await api.get("anya", "/api/tasks")).json()
    assert {t["external_id"] for t in tasks} == {"PAY-214", "PAY-221", "PAY-198"}
    locked = next(t for t in tasks if t["external_id"] == "PAY-198")
    assert locked["locked"] is True
    detail = (await api.get("anya", f"/api/tasks/{locked['id']}")).json()
    assert detail["can_create_chat"] is False
    assert (await api.post("anya", "/api/chats", {"task_id": locked["id"]})).status_code == 409
    assert (await api.get("dima", f"/api/tasks/{locked['id']}")).status_code == 404
    created = await api.post("boris", "/api/mentor/tasks", {"intern_id": "anya", "title": "Логи платежей", "description": "Панель ошибок",
                                                             "deadline": "2026-12-01"})
    assert created.status_code == 201 and created.json()["status"] == "new"
    chats = (await api.get("anya", "/api/chats")).json()
    folder = next(f for f in chats["tasks"] if f["task"]["title"] == "Логи платежей")
    assert folder["chats"] == []
    notes = (await api.get("anya", "/api/notifications")).json()["items"]
    assert notes[0]["text"] == "Наставник создал задачу «Логи платежей»"
    task_id = folder["task"]["id"]
    chat_id = await api.new_chat(task_id=task_id)
    closed = (await api.post("anya", "/api/dev/tracker/update-task", {"task_id": task_id, "status": "done", "shift_days": 3})).json()
    assert closed["locked"] is True and closed["deadline"] == "2026-12-04"
    r = await api.post("anya", f"/api/chats/{chat_id}/messages", {"text": "Как создать dev-ветку?"})
    assert r.status_code == 409
    assert (await api.get("anya", f"/api/chats/{chat_id}/messages")).status_code == 200
    assert (await api.post("anya", "/api/mentor/tasks", {"intern_id": "anya", "title": "x"})).status_code == 403
    assert (await api.post("boris", "/api/mentor/tasks", {"intern_id": "ghost", "title": "x"})).status_code == 404
    dev = (await api.post("anya", "/api/dev/tracker/create-task", {"intern_id": "dima", "title": "Тестовая задача"})).json()
    assert dev["title"] == "Тестовая задача"
    assert (await api.post("anya", "/api/dev/tracker/update-task", {"task_id": "nope", "status": "done"})).status_code == 404


async def test_chat_crud(api):
    chat_id = await api.new_chat()
    patched = (await api.patch("anya", f"/api/chats/{chat_id}", {"title": "Мой чат", "include_in_journal": True, "mode": "direct"})).json()
    assert patched["title"] == "Мой чат" and patched["include_in_journal"] is True and patched["mode"] == "direct"
    events = await api.ask("Что такое грумминг?", chat_id)
    assert first(events, "done")
    data = (await api.get("anya", f"/api/chats/{chat_id}/messages")).json()
    assert data["chat"]["title"] == "Мой чат" and len(data["messages"]) == 2
    assert (await api.post("anya", "/api/chats", {"task_id": "nope"})).status_code == 404
    auto = await api.new_chat()
    await api.ask("Где лежит конфиг Billing?", auto)
    history = (await api.get("anya", "/api/chats")).json()["history"]
    assert next(c for c in history if c["id"] == auto)["title"] == "Где лежит конфиг Billing?"


async def test_dev_panel_day_reset_sync_and_service_endpoints(api):
    assert (await api.post("anya", "/api/dev/advance-day", {"days": 20})).json()["day_offset"] == 20
    assert (await api.get("anya", "/api/home")).json()["stage"]["id"] == "eq"
    assert (await api.post("anya", "/api/dev/advance-day", {"intern_id": "ghost"})).status_code == 404
    assert (await api.post("anya", "/api/dev/sync")).json()["synced_interns"] == 2
    health = (await api.client.get("/api/health")).json()
    assert health["db"] is True and health["mcp"] is True and health["llm_provider"] == "fake"
    assert (await api.post("anya", "/api/events", {"name": "privacy_opened"})).status_code == 202
    assert (await api.post("anya", "/api/events", {"name": "hack"})).status_code == 400
    assert (await api.get("anya", "/api/flags")).json()["guide_mode_default"] == "guide"
    await api.ask("Кто отвечает за сервис платежей?")
    summary = (await api.get("boris", "/api/metrics/summary")).json()
    assert summary["events"]["person_card_shown"] >= 1 and 0 <= summary["led_to_person"] <= 1
    assert (await api.get("anya", "/api/metrics/summary")).status_code == 403
    prom = (await api.client.get("/api/metrics")).text
    assert "buddy_events_total" in prom
    presets = (await api.get("anya", "/api/access/presets")).json()
    assert any(f["key"] == "cost_center" for f in presets["fields"])
    assert (await api.post("anya", "/api/dev/reset")).json()["reset"] is True
    assert len((await api.client.get("/api/auth/users")).json()) == 4


async def test_dev_mode_off_hides_dev_endpoints(api, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "dev_mode", False)
    assert (await api.post("anya", "/api/dev/sync")).status_code == 404
