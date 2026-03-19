.PHONY: dev worker beat migrate shell test lint install setup

install:
	pip install -r requirements-dev.txt

setup:
	python manage.py setup_agentqueue

migrate:
	python manage.py migrate

shell:
	python manage.py shell_plus

dev:
	daphne -b 127.0.0.1 -p 3333 config.asgi:application

worker:
	celery -A celery_app worker -l info

beat:
	celery -A celery_app beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

test:
	pytest

lint:
	ruff check .
	black --check .

fmt:
	black .
	ruff check --fix .
