lint:
	ruff check src/
	ruff format src/
reset:
	.venv/bin/python src/partdb/main.py dumpdb
	.venv/bin/python src/partdb/main.py dropdb
	.venv/bin/python src/partdb/main.py initdb
	.venv/bin/python src/partdb/main.py loaddb
	#.venv/bin/python src/partdb/main.py update_embeddings
