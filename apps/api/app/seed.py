"""Мок-данные (глава 16 ТЗ). Всё вымышленное: «Тестовые данные, не регламенты Авито»."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.retrieval import index_documents, load_wiki
from app.db import utcnow
from app.domain import today
from app.llm.base import Embedder
from app.mcp_client import McpClient
from app.models import (AccessFormPreset, Chat, ChecklistStep, Contact, InternProfile, InternStep, JournalEntry, Message, Notification,
                        Task, Team, User)
from app.services.tasks import sync_tasks

USERS = [
    ("anya", "Аня Соколова", "intern", "f", "Стажёр"),
    ("dima", "Дима Орлов", "intern", "m", "Стажёр"),
    ("boris", "Борис Н.", "mentor", "m", "Наставник"),
    ("maria", "Мария К.", "lead", "f", "Тимлид Payments"),
]

STEPS = [
    ("pre-docs", "pre", "Подписать документы и согласие на обработку ПДн", None),
    ("pre-letter", "pre", "Получить письмо о первом дне", None),
    ("pre-mentor", "pre", "Познакомиться с наставником онлайн", None),
    ("d1-laptop", "d1", "Получить ноутбук и пропуск", None),
    ("d1-mail", "d1", "Войти в почту и Mattermost", None),
    ("d1-vpn", "d1", "Настроить VPN", None),
    ("d1-team", "d1", "Познакомиться с командой на планёрке", None),
    ("w1-welcome", "w1", "Прочитать «Добро пожаловать в Payments»", None),
    ("w1-clone", "w1", "Склонировать billing-service и собрать проект", None),
    ("w1-tests", "w1", "Запустить тесты локально", None),
    ("w1-glossary", "w1", "Разобраться в глоссарии команды", None),
    ("w1-rituals", "w1", "Сходить на ритуалы: планёрка, статус, ревью", None),
    ("w24-1on1", "w24", "Первая встреча 1:1 с наставником", None),
    ("w24-access", "w24", "Запросить доступ к Jira-проекту PAY", "access"),
    ("w24-stand", "w24", "Получить доступ к тестовому стенду", "stand"),
    ("w24-git", "w24", "Освоить git-flow: dev-ветка и pull request", "git"),
    ("w24-grafana", "w24", "Разобраться с дашбордами Billing в Grafana", "grafana"),
    ("w24-first-pr", "w24", "Взять первую задачу и открыть PR", None),
    ("eq-goals", "eq", "Обсудить с наставником цели второй половины", None),
    ("eq-demo", "eq", "Показать свою задачу на демо команды", None),
    ("eq-plan", "eq", "Обновить план развития", None),
    ("fin-journal", "fin", "Собрать журнал достижений", None),
    ("fin-final", "fin", "Итоговая встреча с наставником и лидом", None),
]

PRESET_FIELDS = [
    {"key": "project_key", "label": "Ключ проекта Jira", "type": "string", "required": True},
    {"key": "justification", "label": "Обоснование", "type": "text", "required": True},
    {"key": "level", "label": "Уровень доступа", "type": "enum", "options": ["read", "write", "administration"], "required": True},
    {"key": "space_or_page", "label": "Страница или пространство Confluence", "type": "string", "required": False},
    {"key": "watch_issue_types", "label": "Наблюдение за задачами", "type": "list", "required": False},
    {"key": "cost_center", "label": "Центр затрат (поле команды)", "type": "string", "required": True},
]


def _src(doc_id: str, title: str, system: str, updated: str, url: str) -> dict:
    return {"document_id": doc_id, "title": title, "url": url, "system": system, "updated_at": updated}


async def is_seeded(session: AsyncSession) -> bool:
    return (await session.execute(select(func.count()).select_from(User))).scalar_one() > 0


async def seed_all(session: AsyncSession, mcp: McpClient, embedder: Embedder, seed_dir: str) -> None:
    session.add(Team(id="payments", name="Payments"))
    for uid, name, role, gender, title in USERS:
        session.add(User(id=uid, name=name, email=f"{uid}@example.test", role=role, team_id="payments", gender=gender, title=title))
    await session.flush()
    t = today()
    session.add(InternProfile(user_id="anya", mentor_id="boris", lead_id="maria", hrbp_id="sveta", start_date=t - timedelta(days=11),
                              program_months=6, region="Москва", repos=["billing-service"], jira_projects=["PAY"], learning_budget=60000))
    session.add(InternProfile(user_id="dima", mentor_id="boris", lead_id="maria", hrbp_id="sveta", start_date=t - timedelta(days=3),
                              program_months=6, region="Казань", repos=["billing-service"], jira_projects=["PAY"], learning_budget=60000,
                              is_absent_today=True))
    for order, (sid, stage, title, topic) in enumerate(STEPS):
        session.add(ChecklistStep(id=sid, stage=stage, order=order, title=title, topic=topic, source_doc_id="checklist"))
    await session.flush()
    anya_status = {s[0]: ("done" if s[1] in ("pre", "d1", "w1") else "todo") for s in STEPS}
    anya_status.update({"w24-1on1": "done", "w24-git": "in_progress", "w24-first-pr": "in_progress"})
    dima_status = {s[0]: ("done" if s[1] == "pre" else "todo") for s in STEPS}
    dima_status.update({"d1-mail": "done", "d1-vpn": "done", "d1-team": "done", "w1-welcome": "done"})
    for intern_id, statuses in (("anya", anya_status), ("dima", dima_status)):
        for sid, status in statuses.items():
            session.add(InternStep(intern_id=intern_id, step_id=sid, status=status))
    session.add(AccessFormPreset(team_id="payments", fields=PRESET_FIELDS))

    await index_documents(session, load_wiki(seed_dir), embedder)
    tasks = {task.external_id: task for task in await sync_tasks(session, mcp, "anya", notify_changes=False)}
    await sync_tasks(session, mcp, "dima", notify_changes=False)
    await _seed_anya_history(session, tasks)
    await session.commit()


async def _seed_anya_history(session: AsyncSession, tasks: dict[str, Task]) -> None:
    now = utcnow()

    def chat(title: str, days_ago: float, **kw) -> Chat:
        at = now - timedelta(days=days_ago)
        c = Chat(user_id="anya", title=title, created_at=at, updated_at=at, **kw)
        session.add(c)
        return c

    def msg(c: Chat, role: str, content: str, minutes: int = 0, **kw) -> Message:
        m = Message(chat_id=c.id, role=role, content=content, created_at=c.created_at + timedelta(minutes=minutes), **kw)
        session.add(m)
        return m

    stand = chat("Доступ к тестовому стенду", 1, unresolved=True)
    config = chat("Где лежит конфиг Billing", 4, include_in_journal=True)
    absence = chat("Как оформить отгул", 6)
    groom = chat("Что такое грумминг", 7)
    branch = chat("Как создать dev-ветку", 1.2, task_id=tasks["PAY-214"].id, guide_topic="git", guide_streak=2)
    await session.flush()

    general = _src("stand-general", "Доступ к тестовым стендам (общая инструкция)", "Confluence", "2025-03-14",
                   "https://wiki.example.test/common/stands")
    msg(stand, "user", "Как получить доступ к тестовому стенду?")
    msg(stand, "assistant", "По общей инструкции доступ к тестовому стенду оформляется через заявочную систему, согласует руководитель, а "
        "доступ выдаётся вместе с общим VPN.", 1, route="lookup", mode="guide", sources=[general], feedback="no",
        meta={"steps": ["Ищу в вики", "Нашёл 1 страницу", "Формирую ответ"], "question": "Как получить доступ к тестовому стенду?"})

    readme = _src("billing-readme", "Billing README", "Bitbucket", "2026-10-30", "https://bitbucket.example.test/pay/billing-service/README.md")
    msg(config, "user", "Где лежит конфиг Billing?")
    msg(config, "assistant", "Конфиг Billing лежит в репозитории billing-service, папка /config. Значения для тестовых стендов — в "
        "/config/stands. Секретов в репозитории нет: они хранятся в хранилище секретов, доступ выдаёт DevOps.", 1, route="lookup",
        mode="guide", sources=[readme], feedback="yes",
        meta={"steps": ["Ищу в вики", "Нашёл 1 страницу", "Формирую ответ"], "hint": "Разобралась, как устроены конфиги Billing для стендов.",
              "question": "Где лежит конфиг Billing?"})

    absence_src = _src("absence", "Как оформить отгул (тест, уточните по ТК РФ)", "Confluence", "2026-09-01",
                       "https://wiki.example.test/common/absence")
    msg(absence, "user", "Как оформить отгул?")
    msg(absence, "assistant", "Отгул и отпуск — разные процессы. Сначала договоритесь об отгуле с руководителем, затем оформите отсутствие "
        "через HR BP. Конкретные нормы и сроки уточняйте по ТК РФ у HR.", 1, route="lookup", mode="guide", sources=[absence_src],
        blocks=[{"type": "person_card", "person_id": "maria", "name": "Мария К.", "role": "Тимлид Payments", "team": "Payments",
                 "handle": "@maria.k", "reason": "Руководитель: доступы к проектам, отсутствия, техника, цели",
                 "how_to_ask": "Мария, добрый день! Хочу взять отгул. Подскажете, удобно ли согласовать?", "questions": [],
                 "duration": "обычно 20 минут", "compact": False, "note": None,
                 "chain": [{"id": "sveta", "name": "Света М.", "role": "HR BP"}], "chain_label": "Порядок обращения"}],
        meta={"steps": ["Ищу в вики", "Нашёл 1 страницу", "Формирую ответ"], "question": "Как оформить отгул?"})

    glossary = _src("glossary", "Глоссарий команды (скрам, грумминг, ревью)", "Confluence", "2026-09-12", "https://wiki.example.test/payments/glossary")
    msg(groom, "user", "Что такое грумминг?")
    msg(groom, "assistant", "Грумминг — встреча, на которой команда разбирает задачи из бэклога: уточняет требования, оценивает и решает, "
        "что брать в спринт. В Payments грумминг проходит по средам в 11:00.", 1, route="lookup", mode="guide", sources=[glossary],
        feedback="yes", meta={"steps": ["Ищу в вики", "Нашёл 1 страницу", "Формирую ответ"], "question": "Что такое грумминг?"})

    gitpr = _src("git-pr", "Как создать dev-ветку и открыть pull request", "Confluence", "2026-10-02", "https://wiki.example.test/payments/git-flow")
    msg(branch, "user", "Как создать dev-ветку?")
    msg(branch, "assistant", "Давайте разберёмся так, чтобы вы запомнили порядок.\n\n**Вопрос:** какой ключ у вашей задачи в трекере? "
        "Он понадобится в имени ветки.\n\n**Где искать:** инструкция «Как создать dev-ветку и открыть pull request», раздел «Именование веток».",
        1, route="howto", mode="guide", sources=[gitpr],
        meta={"steps": ["Ищу в вики", "Формирую наводящий вопрос"], "guide": {"step": 1, "total": 2, "topic": "git"},
              "hint": "Разобралась в git-flow команды и создала dev-ветку по правилам.", "question": "Как создать dev-ветку?"})
    msg(branch, "user", "Ключ задачи — PAY-214", 4)
    msg(branch, "assistant", "Хорошо. Теперь проверьте: от какой ветки создаётся новая — от `main` или от `dev`?\n\n**Где искать:** та же "
        "инструкция, раздел «Порядок работы». Если не найдёте, следующий ответ будет прямым.", 5, route="howto", mode="guide", sources=[gitpr],
        meta={"steps": ["Ищу в вики", "Формирую наводящий вопрос"], "guide": {"step": 2, "total": 2, "topic": "git"},
              "hint": "Разобралась в git-flow команды и создала dev-ветку по правилам.", "question": "Ключ задачи — PAY-214"})

    session.add(Contact(intern_id="anya", person_id="boris", name="Борис Н.", role="Наставник", team="Payments",
                        topics=["Первая задача", "Код-ревью", "Процессы команды"],
                        how_to_ask="Писать в Mattermost в личку, коротко и с контекстом: что уже проверили.",
                        note="Удобно писать до 12:00. 1:1 по пятницам.", created_at=now - timedelta(days=11)))
    session.add(Contact(intern_id="anya", person_id="oleg", name="Олег Р.", role="DevOps, тестовые стенды", team="Platform",
                        topics=["Тестовые стенды", "CI/CD", "Деплой и секреты"],
                        how_to_ask="Олег, добрый день! Я стажёр в Payments, оформляю доступ к тестовому стенду. Подскажете, какая инструкция актуальна?",
                        source_chat_id=stand.id, source_chat_title=stand.title, created_at=now - timedelta(days=1)))
    session.add(JournalEntry(intern_id="anya", text="Собрала billing-service локально, прогнала тесты и разобралась, где лежат конфиги для "
                             "тестовых стендов.", source_chat_id=config.id, source_chat_title=config.title, created_at=now - timedelta(days=4)))
    session.add(JournalEntry(intern_id="anya", text="Сходила на все ритуалы команды и подготовила вопросы к первой встрече 1:1 с наставником.",
                             source_chat_id=None, source_chat_title="Вопросы к первой 1:1", created_at=now - timedelta(days=6)))
    session.add(Notification(user_id="anya", kind="task", text="Наставник создал задачу «Гайд по ревью»",
                             target={"route": "task", "id": tasks["PAY-221"].id}, created_at=now - timedelta(hours=3)))
    session.add(Notification(user_id="anya", kind="task", text="Наставник создал задачу «Платёжный модуль»", read=True,
                             target={"route": "task", "id": tasks["PAY-214"].id}, created_at=now - timedelta(days=8)))
