SHELL := /bin/sh

.PHONY: install lint format check test migrations migrate run superuser

install:
	poetry install

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

check:
	poetry run python manage.py check

test:
	poetry run pytest

migrations:
	poetry run python manage.py makemigrations

migrate:
	poetry run python manage.py migrate

run:
	poetry run python manage.py runserver

superuser:
	poetry run python manage.py createsuperuser
