---
id: git-pr
title: Как создать dev-ветку и открыть pull request
url: https://wiki.example.test/payments/git-flow
system: Confluence
owner: boris
team: payments
access_level: team
space: team
updated_at: 2026-10-02
---
## Именование веток
Ветка называется по шаблону feature/<ключ задачи>-<короткое описание>, например feature/PAY-214-refund-status.

## Порядок работы
Новую ветку создают от dev: git checkout dev, git pull, затем git checkout -b с именем по шаблону. После первого коммита отправьте ветку и откройте черновой pull request в dev.

## Pull request
Pull request открывается в ветку dev. Ревьюеры назначаются автоматически по CODEOWNERS.
