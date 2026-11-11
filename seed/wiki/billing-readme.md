---
id: billing-readme
title: Billing README
url: https://bitbucket.example.test/pay/billing-service/README.md
system: Bitbucket
owner: igor
team: payments
access_level: team
space: team
updated_at: 2026-10-30
---
## О сервисе
Billing — сервис приёма и учёта платежей. Владелец сервиса — Игорь Л., он указан в CODEOWNERS для /services/billing/.

## Статусы платежа
Статусы платежа описаны в модуле services/billing/status: created, paid, cancelled. Обработка статуса «отменён» — хороший образец для новых статусов. Тесты лежат рядом, в tests/status.

## Конфиг
Конфиг Billing лежит в репозитории billing-service, папка /config. Значения для тестовых стендов — в /config/stands. Секретов в репозитории нет: они хранятся в хранилище секретов, доступ выдаёт DevOps.

## Где лежит код
Код сервиса — в Bitbucket, репозиторий billing-service. Склонировать: git clone ssh://bitbucket.example.test/pay/billing-service.git
