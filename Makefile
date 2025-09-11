.PHONY: dev start db-init seed fmt

dev:
	python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

start:
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

db-init:
	alembic upgrade head

seed:
	python -m app.scripts.seed

fmt:
	python -m pip install ruff black && ruff check --fix . || true && black . || true
