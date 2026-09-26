lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

backup *args:
	scripts/backup-local.sh {{args}}

verify-backup path:
	scripts/verify-backup.sh "{{path}}"
