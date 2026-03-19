.PHONY: dev worker beat migrate shell test lint install setup

install:
	.venv/bin/pip install -r requirements-dev.txt

setup:
	.venv/bin/python manage.py setup_agentqueue

migrate:
	.venv/bin/python manage.py migrate

shell:
	.venv/bin/python manage.py shell_plus

dev:
	.venv/bin/daphne -b 0.0.0.0 -p 3333 config.asgi:application

worker:
	.venv/bin/celery -A celery_app worker -l info

beat:
	.venv/bin/celery -A celery_app beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

test:
	.venv/bin/pytest

lint:
	ruff check .
	black --check .

fmt:
	black .
	ruff check --fix .
