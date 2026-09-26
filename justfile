install:
	uv sync --locked --all-extras

up:
	docker compose up -d --wait
	uv run partdb db migrate

migrate:
	uv run partdb db migrate

down:
	docker compose down

test:
	docker compose up -d --wait
	uv run pytest -v

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

backup *args:
	scripts/backup-local.sh {{args}}

verify-backup path:
	scripts/verify-backup.sh "{{path}}"
