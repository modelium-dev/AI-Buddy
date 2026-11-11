API=apps/api
PY?=python

.PHONY: up down seed test coverage eval lint check-llm demo-reset install

install:
	cd $(API) && $(PY) -m pip install -e ".[dev]"

up:
	test -f .env || cp .env.example .env
	docker compose up --build

down:
	docker compose down

seed:
	docker compose exec api python -m app.cli seed

demo-reset:
	curl -s -X POST http://localhost:8000/api/dev/reset

test:
	cd $(API) && $(PY) -m pytest -q

coverage:
	cd $(API) && $(PY) -m pytest -q --cov=app --cov-report=term --cov-report=xml:coverage.xml --cov-fail-under=80

eval:
	cd $(API) && $(PY) -m app.cli eval

lint:
	cd $(API) && $(PY) -m ruff check app tests

check-llm:
	docker compose exec api python -m app.cli check-llm
