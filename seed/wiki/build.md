---
id: build
title: Как собрать проект и запустить тесты
url: https://wiki.example.test/payments/build
system: Confluence
owner: boris
team: payments
access_level: team
space: team
updated_at: 2026-10-20
---
## Сборка
Склонируйте репозиторий billing-service и выполните make build. Для сборки нужен доступ к Bitbucket и VPN.

## Тесты
Тесты запускаются командой make test, линтер — make lint. Если тесты падают на импорте модуля, проверьте, что установлены зависимости командой make deps.
