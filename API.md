# API «Путь стажёра» — справочник для фронтенда

Базовый адрес: `http://localhost:8000/api`. Живая схема OpenAPI: `http://localhost:8000/docs`.
Все данные тестовые, не регламенты Авито.

## Общие правила

| Что | Как |
|---|---|
| Формат | JSON, UTF-8. Даты — ISO 8601 (`2026-11-13`, `2026-11-11T09:15:00`, время в UTC без зоны) |
| Авторизация | `Authorization: Bearer <access_token>` из `POST /auth/login`. Регистрации нет |
| Ошибки | `{"error": {"code": "...", "message": "..."}}` |
| Коды ошибок | `401 unauthorized`, `403 forbidden`, `404 not_found`, `409 conflict`, `400/422 invalid_input`, `413 too_large`, `415 unsupported_type`, `429 rate_limited`, `502/503` — сервис-имитация недоступен |
| Роли | `intern` (стажёр), `mentor` (наставник), `lead` (лид, экрана нет) |
| Приватность | Все ручки чатов, сообщений, вложений, знакомств, журнала, практики, приватности и заявок — только `intern`. Наставник и лид получают **403** (попытка пишется в журнал доступа стажёра). Чужой `id` другого стажёра — **404** |
| Стриминг | Ответ ассистента — **SSE** (`text/event-stream`), см. раздел «SSE-события» |

Тестовые пользователи: `anya` (стажёр, день 12, основной сценарий), `dima` (стажёр, день 4, пустые состояния, «сегодня в отгуле»),
`boris` (наставник), `maria` (лид).

---

## 1. Авторизация и профиль

### `GET /auth/users` — список тестовых пользователей (без токена)
```json
[{"id": "anya", "name": "Аня Соколова", "role": "intern", "title": "Стажёр", "can_login": true}]
```

### `POST /auth/login`
Тело: `{"user_id": "anya"}` → 
```json
{"access_token": "eyJ...", "token_type": "bearer", "user": { ...как в GET /me... }}
```

### `GET /me` — профиль
```json
{
  "id": "anya", "name": "Аня Соколова", "role": "intern", "team_id": "payments", "title": "Стажёр", "gender": "f",
  "intern": {"day": 12, "total_days": 180, "stage": {"id": "w24", "label": "Недели 2–4"}, "mentor_id": "boris", "lead_id": "maria",
             "hrbp_id": "sveta", "program_months": 6, "region": "Москва", "repos": ["billing-service"], "jira_projects": ["PAY"],
             "learning_budget": 60000, "is_absent_today": false},
  "privacy": {"share_topics": false, "seen_privacy": false, "first_entry_text": "Здесь можно задавать любые вопросы. ..."}
}
```
Поля `intern` и `privacy` есть только у стажёра. Если `privacy.seen_privacy == false` — показать окно первого входа.

### `POST /me/privacy-ack` (intern) — окно первого входа просмотрено → `{"seen_privacy": true}`

---

## 2. Главная («Новый чат»), чек-лист, практика, уведомления

### `GET /home` (intern)
```json
{
  "stage": {"id": "w24", "label": "Недели 2–4"}, "day": 12, "total_days": 180,
  "stages": [{"id": "pre", "label": "До старта", "state": "done", "progress": null},
             {"id": "w24", "label": "Недели 2–4", "state": "current", "progress": 0.24}],
  "normalization_text": "На 2–4 неделе почти у всех ощущение, что задач мало, а ожиданий много. Это нормально.",
  "digest": {"text": "В последний раз вы разбирались с вопросом «...». Не решено: ...", "chat_id": "c1", "chat_title": "...", "unresolved": true},
  "next_step": {"step_id": "w24-access", "title": "Запросить доступ к Jira-проекту PAY", "topic": "access", "status": "todo",
                "note": "Шаблон. В вашей команде может отличаться."},
  "tasks_today": [{"id": "t1", "title": "Платёжный модуль", "status": "in_progress", "deadline": "2026-11-13"}],
  "suggestions": ["Кто отвечает за сервис платежей?", "Как запросить доступ к Jira-проекту PAY?", "Что делать дальше?"],
  "notifications": [{"id": "n1", "kind": "task", "text": "Наставник создал задачу «Гайд по ревью»", "target": {"route": "task", "id": "t2"},
                     "created_at": "..."}],
  "privacy_note": "Ваши чаты видите только вы"
}
```
* `stages[].state`: `done | current | next`; `progress` (0..1) только у текущего этапа.
* Блок «На чём остановились» → `digest` (кнопка «Продолжить» открывает `digest.chat_id`).
* Блок «Следующий шаг» → `next_step` (кнопки «Спросить ассистента» → отправить вопрос в новый чат; «Дай практику» → `POST /checklist/{step_id}/practice`).
* `notifications` — только непрочитанные (для бейджа).

### `GET /checklist` (intern)
```json
{"note": "Шаблон, а не обязательство...", "current_stage": "w24",
 "stages": [{"id": "w24", "label": "Недели 2–4", "current": true, "done": 1, "total": 6,
             "steps": [{"id": "w24-access", "title": "Запросить доступ к Jira-проекту PAY", "topic": "access", "has_practice": true, "status": "todo"}]}]}
```
`status`: `todo | in_progress | done | hidden` (`hidden` — «не про нашу команду»).

### `PATCH /checklist/{step_id}` (intern) — тело `{"status": "done"}` → `{"step_id": "...", "status": "done"}`

### `POST /checklist/{step_id}/practice` (intern) — сгенерировать 1–3 микро-задания
```json
{"step_id": "w24-grafana", "topic": "grafana", "label": "Grafana",
 "items": [{"id": "p1", "task": "Найдите в Grafana два дашборда сервиса Billing", "criterion": "записаны названия обоих дашбордов", "status": "open"}]}
```
400 `no_practice`, если у шага нет практики.

### `GET /practice` (intern) — все микро-задания стажёра (`[{id, step_id, topic, task, criterion, status, message_id, created_at}]`)
### `PATCH /practice/{id}` (intern) — `{"status": "done" | "open"}` → объект задания

### `GET /notifications` (любая роль) → `{"unread": 1, "items": [{"id", "kind", "text", "target", "read", "created_at"}]}`
`kind`: `task | access | doc_issue | system`. `target` подсказывает, куда вести: `{"route": "task", "id": "..."}`, `{"route": "chat", "id": "...", "action_id": "..."}`, `{"route": "mentor"}`.
### `POST /notifications/{id}/read` → уведомление · `POST /notifications/read-all` → `{"unread": 0}`

---

## 3. Чаты и сообщения

### `GET /chats` (intern) — левое меню: папки задач и история
```json
{
  "tasks": [{"task": { ...Task... }, "chats": [ ...Chat... ]}],
  "history": [ ...Chat... ],
  "empty_tasks_text": "Пока задач нет. Они появятся, когда наставник создаст задачу."
}
```
**Chat**: `{"id", "title", "task_id", "mode": "guide|direct", "include_in_journal", "unresolved", "guide": {"topic", "streak"} | null, "created_at", "updated_at"}`.
`unresolved = true` → показать точку «не решено». История отсортирована: новые сверху.

**Task**: `{"id", "external_id": "PAY-214", "title", "description", "status": "new|in_progress|review|done", "status_label", "deadline", "created_by", "locked", "synced_at"}`.

### `POST /chats` (intern) — `{"task_id": "..."?, "title": "..."?}` → 201 Chat
409, если задача закрыта в трекере (`locked`). Без `title` чат называется «Новый чат» и переименовывается по первому сообщению.

### `PATCH /chats/{id}` (intern) — `{"title"?, "include_in_journal"?, "mode"?}` → Chat
Меню чата: «Переименовать», «Учитывать в журнале».

### `DELETE /chats/{id}` (intern) → 204
Физическое удаление сообщений и вложений. Записи журнала и знакомства остаются (подпись «чат удалён»).

### `GET /chats/{id}/messages` (intern)
```json
{"chat": { ...Chat... }, "task": { ...Task... } | null,
 "messages": [{
   "id": "m1", "chat_id": "c1", "role": "user|assistant", "content": "текст (markdown: **жирный**, `код`, нумерованные списки)",
   "route": "lookup", "mode": "guide", "sources": [ ...Source... ], "blocks": [ ...Block... ],
   "steps": ["Ищу в вики", "Нашёл 3 страницы", "Формирую ответ"], "guide": {"step": 1, "total": 2, "topic": "git"} | null,
   "attachments": [{"id", "kind", "filename"}], "feedback": "yes|no|null", "created_at": "..."}]}
```
* У блоков с `action_id` (`action_draft`, `conflict`) сервер добавляет поле `action` — **актуальное** состояние заявки (см. Action).
* `guide != null` → под сообщением кнопка «Сразу ответ» (`POST /messages/{id}/direct`).
* Для чата задачи над окном показывать `task` (название, статус, дедлайн, свёрнутое описание «Из трекера»). Если `task.locked` — поле ввода отключить.

### `POST /chats/{id}/messages` (intern) — отправить вопрос, ответ **SSE**
Тело: `{"text": "Кто отвечает за сервис платежей?", "mode": "guide" | "direct", "attachment_ids": ["..."]}`.
Заголовок (необязательно): `Idempotency-Key: <uuid>` — повторная отправка с тем же ключом вернёт сохранённый ответ (в `done` будет `"replayed": true`).
Ошибки до начала потока: 409 (задача закрыта), 429 (больше 20 сообщений в минуту).

### `POST /chats/{id}/attachments` (intern) — `multipart/form-data`, поле `file`
Изображение (`png/jpeg/webp/gif`) или лог (`.log`, `.txt`), до 5 МБ → 201
`{"id", "kind": "image|log", "filename", "size", "warning": "Не отправляйте пароли и токены."}`. Затем передайте `id` в `attachment_ids` сообщения.

### `POST /messages/{id}/feedback` (intern) — `{"helpful": true|false}` → `{"message_id", "feedback": "yes|no", "chat_unresolved"}`
«Не помогло» на последнем ответе помечает чат как нерешённый (попадёт в «На чём остановились»).

### `POST /messages/{id}/direct` (intern) — кнопка «Сразу ответ», ответ **SSE**
Прямой ответ на вопрос этого сообщения ассистента (новое сообщение ассистента, без нового сообщения пользователя).

### `POST /messages/{id}/retry` (intern) — «Повторить» после ошибки ИИ, ответ **SSE**
Только для сообщений с `route == "error"`: ошибочное сообщение удаляется, вопрос отвечается заново.

### SSE-события

Формат: `event: <name>\ndata: <json>\n\n`. Порядок: `status`… → `token`… → `source`/блоки… → `done` (или `error` → `done`).

| event | data | Как показывать |
|---|---|---|
| `status` | `{"step": "search", "text": "Ищу в вики"}` | Строка шагов над ответом |
| `token` | `{"text": "кусок текста"}` | Дописывать в текст ответа |
| `source` | Source: `{"document_id", "title", "url", "system": "Confluence\|Bitbucket\|...", "updated_at"}` | Чип источника со ссылкой и датой |
| `person_card` | PersonCard (ниже) | Карточка человека |
| `action_draft` | ActionDraft (ниже) | Карточка действия: «Подтвердить / Изменить / Отмена» |
| `conflict` | Conflict (ниже) | Блок «В документах расхождение» |
| `practice` | `{"topic", "label", "step_id", "items": [{"id", "task", "criterion", "status"}]}` | Список микро-заданий с отметками (`PATCH /practice/{id}`) |
| `next_step` | `{"step_id", "title", "topic", "note", "unresolved_chat_id"}` | Кнопки «Спросить про шаг» и «Дай практику» |
| `notice` | `{"kind": "policy", "title", "text"}` | Нейтральная плашка (например, отказ для глобального пространства) |
| `error` | `{"code": "llm_timeout", "message": "Не получилось ответить. Вот человек, которого можно спросить.", "fallback_person": {"person_id", "name", "role"}}` | Ошибка не блокирует UI; кнопка «Повторить» → `POST /messages/{message_id}/retry` |
| `done` | `{"message_id", "route", "mode", "guide": {"step", "total", "topic"} \| null, "replayed"?: true}` | Конец ответа |

`route`: `lookup | howto | process | access_request | absence_request | practice | no_answer | emotional | out_of_scope | error`.

**PersonCard**
```json
{"person_id": "igor", "name": "Игорь Л.", "role": "Владелец сервиса Billing", "team": "Billing", "handle": "@igor.l",
 "reason": "Владелец /services/billing/ по CODEOWNERS", "how_to_ask": "Игорь, добрый день! ...", "questions": ["...", "..."],
 "duration": "обычно 20 минут", "compact": false, "note": null,
 "chain": [{"id": "boris", "name": "Борис Н.", "role": "Наставник"}, {"id": "web", "name": "Внешний источник", "role": "..."}],
 "chain_label": "Если Игорь Л. недоступен"}
```
* `compact: true` — показывать строкой «Если не получится: …».
* «Сохранить в знакомства» → `POST /contacts` с `person_id`, `how_to_ask` и `source_chat_id`. «Написать» — скопировать `how_to_ask` (отправляет человек сам, в Mattermost).
* `note` — например, «эксперт загружен, предлагаю следующего».

**ActionDraft**
```json
{"action_id": "a1", "type": "access_request" | "absence_request",
 "payload": {"project_key": "PAY", "level": "read", "justification": "...", "space_or_page": "Payments / Платёжный модуль",
             "watch_issue_types": ["Bug", "Story"], "cost_center": "CC-PAY-01"},
 "fields": [{"key": "level", "label": "Уровень доступа", "type": "enum", "options": ["read", "write", "administration"], "required": true}],
 "approver": {"id": "maria", "name": "Мария К.", "role": "Тимлид Payments"},
 "level_hint": "Минимально достаточный уровень ... read" | null}
```
Подпись карточки: «Заявка готова. Проверьте и подтвердите. Отправляет её ваше подтверждение.» Форма строится по `fields` (пресет команды).

**Conflict**
```json
{"variants": [{"document_id": "stand-team", "source": "...(инструкция команды)", "url": "...", "date": "2026-10-28", "team_version": true,
               "steps": ["...", "..."], "summary": "..."},
              {"document_id": "stand-general", "source": "...(общая инструкция)", "date": "2025-03-14", "team_version": false, "steps": ["..."]}],
 "note": "Сначала показываю версию команды...", "action_id": "a2", "draft_message": "Здравствуйте! В двух инструкциях ...",
 "recipients": [{"id": "oleg", "name": "Олег Р.", "role": "владелец «...»"}, {"id": "boris", "name": "Борис Н.", "role": "наставник"}]}
```
«Сообщить владельцу страницы и наставнику» → (необязательно) `PATCH /actions/{action_id}` с `{"text": "..."}` → `POST /actions/{action_id}/confirm`.

---

## 4. Задачи (папки из трекера)

Стажёр папки не создаёт и не удаляет. Задачи синхронизируются с трекером при каждом запросе списка и по расписанию.

### `GET /tasks` (intern) → `[Task]`
### `GET /tasks/{id}` (intern) → Task + `{"chats": [Chat], "can_create_chat": bool, "notes": ["..."]}`
Закрытая в трекере задача: `locked: true`, `can_create_chat: false` — чаты только для чтения.

---

## 5. Действия: заявка на доступ, отгул, сообщение о расхождении

Ассистент только готовит черновик. Отправляет **человек** — отдельной ручкой, не через ИИ.

**Action**
```json
{"id": "a1", "type": "access_request|absence_request|doc_conflict_report", "status": "draft|confirmed|cancelled|failed",
 "external_id": "ACC-1042", "external_status": "pending|granted|rejected|sent|null", "payload": {...},
 "approver_id": "maria", "approver_name": "Мария К., тимлид Payments", "chat_id": "c1", "message_id": "m2",
 "timeline": [{"status": "draft", "text": "Черновик"}, {"status": "confirmed", "text": "Подтверждено вами", "at": "..."},
              {"status": "sent", "text": "Отправлено (ACC-1042)", "at": "..."}, {"status": "pending", "text": "Ждёт согласования у Мария К., тимлид Payments", "at": "..."},
              {"status": "granted", "text": "Доступ выдан", "at": "..."}],
 "checklist_prompt": {"step_id": "w24-access", "title": "Запросить доступ к Jira-проекту PAY"} | null,
 "issue_id": "DOC-17" | null, "error": {"code", "message"} | null, "created_at": "...", "confirmed_at": "..."}
```
Таймлайн для UI: `Черновик → Подтверждено вами → Отправлено (№) → Ждёт согласования у {имя, роль} → Доступ выдан | Отклонено`.
Если пришёл `checklist_prompt` — спросить стажёра «Отметить шаг выполненным?» и при согласии вызвать `PATCH /checklist/{step_id}` `{"status": "done"}`.

| Метод | Путь | Описание |
|---|---|---|
| GET | `/access/presets` | Пресет полей заявки команды: `{"team", "fields": [...], "defaults": {...}, "levels": [...]}` |
| GET | `/actions?type=access_request` | Все действия стажёра (новые сверху) |
| GET | `/actions/{id}` | Состояние и таймлайн |
| PATCH | `/actions/{id}` | Правка черновика (только `draft`, иначе 409). Поля: `project_key, justification, level, space_or_page, watch_issue_types, cost_center` · для отгула `date_from, date_to, kind, reason` · для расхождения `text` |
| POST | `/actions/{id}/confirm` | Подтверждение. **Идемпотентно** (повтор вернёт то же). 403 — глобальное пространство (статус станет `failed`) |
| POST | `/actions/{id}/cancel` | Отмена черновика → `cancelled` («Ничего не отправлено») |
| GET | `/actions/{id}/reminder` | Черновик напоминания согласующему, если заявка долго ждёт: `{"text", "channel": "Mattermost", "sent": false}` |

---

## 6. Знакомства (видит только стажёр)

**Contact**: `{"id", "person_id", "name", "role", "team", "topics": [], "how_to_ask", "note", "source_chat_id", "source_chat_title", "created_at"}`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/contacts?q=текст` | Список с поиском по имени, роли, темам, заметке |
| POST | `/contacts` | Из карточки: `{"person_id": "igor", "how_to_ask": "...", "source_chat_id": "..."}` (имя, роль, темы подтянутся). Вручную: `{"name", "role", "team", "topics", "note"}`. 409 — человек уже сохранён |
| PATCH | `/contacts/{id}` | `{"note"?, "role"?, "team"?, "topics"?, "how_to_ask"?}` |
| DELETE | `/contacts/{id}` | 204 |

---

## 7. Журнал достижений

**JournalEntry**: `{"id", "text", "source_chat_id", "source_chat_title", "chat_deleted", "source_label": "Из чата «…» | Чат удалён · «…» | Добавлено вручную", "include_in_export", "shared_with_mentor", "created_at"}`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/journal` | `{"note": "Запись остаётся в журнале, даже если удалить чат. ...", "entries": [...]}` |
| POST | `/journal/suggest` | `{"chat_ids": [...]}` → `{"items": [{"text", "chat_id", "chat_title"}], "empty_text"}`. Только по выбранным чатам, **ничего не сохраняет**. По умолчанию отмечайте чаты с `include_in_journal` |
| POST | `/journal` | `{"entries": [{"text", "source_chat_id"?}]}` → 201 `{"entries": [...]}` (снимки текста) |
| PATCH | `/journal/{id}` | `{"text"?, "include_in_export"?, "shared_with_mentor"?}` |
| DELETE | `/journal/{id}` | 204 |
| POST | `/journal/draft` | `{"entry_ids": [...]}` (пусто — все с `include_in_export`) → `{"text", "entry_ids"}` — редактируемый текст |
| POST | `/journal/export` | `{"text", "title"?}` → файл `application/pdf` (`journal.pdf`) |

---

## 8. Приватность

### `GET /privacy` (intern)
```json
{"summary": "Ваши чаты видите только вы. ...",
 "columns": ["intern", "mentor", "lead", "hr", "ai_provider"],
 "matrix": [{"data": "Чаты и вопросы", "intern": "yes", "mentor": "no", "lead": "no", "hr": "no", "ai_provider": "Текст запроса — для ответа"}],
 "flows": [{"title": "Вы задаёте вопрос", "text": "..."}],
 "ai_provider": {"mode": "fake|openai_compatible", "host": "api.example.com", "model": "...", "external": true},
 "settings": {"share_topics": false}, "checklist_visible_to_mentor_by_default": true,
 "first_entry_text": "...", "access_log": [{"viewer_id", "viewer_name", "resource", "decision": "allow|deny", "reason", "created_at"}]}
```
Ячейки `matrix`: `"yes"`, `"no"` или текст-пояснение.

### `PUT /privacy/settings` — `{"share_topics": true}` → `{"share_topics": true}`
### `DELETE /privacy/chats` — удалить все чаты → `{"deleted": 6, "kept": "Записи журнала и знакомства остались"}`

---

## 9. Наставник (P1)

### `GET /mentor/interns` (mentor)
```json
{"note": "Чаты, вопросы и знакомства стажёров недоступны...",
 "interns": [{
   "intern": {"id": "anya", "name": "Аня Соколова", "team": "payments", "day": 12, "total_days": 180, "stage": {"id": "w24", "label": "Недели 2–4"}},
   "is_absent_today": false,
   "checklist": {"done": 13, "total": 23, "current_stage": [{"id", "title", "status"}]},
   "tasks": [Task], "access_requests": [{"id", "number", "project_key", "level", "status"}],
   "absences": [{"id", "number", "date_from", "status"}], "doc_issues": [{"id", "summary", "document_ids", "status", "created_at"}],
   "shared_journal": [{"id", "text", "created_at"}], "help_template": "...", "one_to_one_phrase": "...",
   "topic": "Платёжный модуль", "chats_access": "denied"}]}
```
Поле `topic` **отсутствует**, если стажёр не разрешил показывать тему (показывать нейтрально, без пометок).

### `POST /mentor/tasks` (mentor) — `{"intern_id": "anya", "title": "...", "description": "...", "deadline": "2026-12-01"}` → 201 Task
У стажёра появляется пустая папка и уведомление «Наставник создал задачу …».

---

## 10. Служебные

| Метод | Путь | Кто | Описание |
|---|---|---|---|
| GET | `/health` | все | `{"status", "db", "mcp", "llm_provider", "dev_mode"}` |
| POST | `/events` | авторизованные | `{"name", "props"}` → 202. Имена: `chat_created, message_sent, answer_helpful, answer_not_helpful, direct_answer_clicked, person_card_shown, contact_saved, access_draft_shown, access_confirmed, access_granted, conflict_shown, conflict_reported, practice_generated, practice_done, checklist_step_done, journal_entry_added, journal_exported, privacy_opened` (большинство сервер пишет сам) |
| GET | `/flags` | авторизованные | Флаги, например `{"guide_mode_default": "guide"}` — режим по умолчанию для A/B |
| GET | `/knowledge/search?q=` | авторизованные | Поиск по базе знаний с правами роли (лид видит документы `lead`, стажёр — нет) |
| GET | `/metrics/summary` | mentor, lead | Доли «закрыто без человека» / «привёл к человеку», «Не помогло», «Сразу ответ», заявки |
| GET | `/metrics` | все | Prometheus-формат |

## 11. Dev-панель (только `DEV_MODE=true`, иначе 404)

| Метод | Путь | Тело | Что делает |
|---|---|---|---|
| POST | `/dev/tracker/create-task` | `{"intern_id", "title", "description"?, "deadline"?}` | Задача от наставника (имитация трекера) |
| POST | `/dev/tracker/update-task` | `{"task_id", "status"?, "deadline"?, "description"?, "shift_days"?}` | Сменить статус/срок. `done` блокирует папку |
| POST | `/dev/access/approve` | `{"action_id"}` | Согласовать заявку → уведомление «Доступ выдан» + `checklist_prompt` |
| POST | `/dev/access/reject` | `{"action_id", "reason"?}` | Отклонить заявку |
| POST | `/dev/advance-day` | `{"days": 7, "intern_id": "anya"}` | Сдвинуть день стажировки (меняет этап) |
| POST | `/dev/llm/fail-next` | `{"enabled": true}` | Следующий ответ ИИ завершится ошибкой (проверка состояния ошибки) |
| POST | `/dev/sync` | — | Синхронизировать задачи всех стажёров |
| POST | `/dev/reset` | — | Сбросить демо-данные |

---

## Быстрый пример (fetch + SSE)

```js
const { access_token } = await (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({user_id: 'anya'})})).json();
const auth = {Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json'};
const chat = await (await fetch('/api/chats', {method: 'POST', headers: auth, body: '{}'})).json();
const res = await fetch(`/api/chats/${chat.id}/messages`, {method: 'POST', headers: {...auth, 'Idempotency-Key': crypto.randomUUID()},
  body: JSON.stringify({text: 'Кто отвечает за сервис платежей?', mode: 'guide'})});
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buf = '';
for (;;) {
  const {value, done} = await reader.read(); if (done) break;
  buf += value; let i;
  while ((i = buf.indexOf('\n\n')) >= 0) {
    const block = buf.slice(0, i); buf = buf.slice(i + 2);
    const event = /^event: (.*)$/m.exec(block)?.[1]; const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null');
    console.log(event, data); // status | token | source | person_card | action_draft | conflict | practice | next_step | notice | error | done
  }
}
```
`EventSource` не подходит (он умеет только GET) — читайте поток через `fetch`, как выше.
