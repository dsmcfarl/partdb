# partdb

A tool for keeping track of where parts are stored. This tool is optimzed for use by hobbyists and is not intended as an inventory management system for businesses. For example, it does not even try to keep track of quantities.

## Features

* Keep track of parts and their locations
* Search for parts using either full text or semantic (vector) search by part description

## Requirements

- An OpenAI API key for creating embeddings of part descriptions; environment variable `OPENAI_API_KEY` must be set and exported.
- A PostgreSQL database server with the pgvector extension available; e.g.,[pgvector docker image](https://hub.docker.com/r/ankane/pgvector).
- a [~/.pg_service.conf](https://www.postgresql.org/docs/current/libpq-pgservice.html) file with a `partdb` service and a `partdb-superuser` service configured and [~/.pgpass](https://www.postgresql.org/docs/current/libpq-pgpass.html) file if appropriate (not required if pg_hba.conf is configured to trust local users for example). An example `~/.pg_service.conf` file is shown below. The user and dbname for the `partdb` service must be `partdb`. The user and dbname for the `partdb-superuser` service must be a postgresql user that has superuser rights.

Example `~/.pg_service.conf` file:
```
[partdb]
host=127.0.0.1
port=5435
user=partdb
dbname=partdb

[partdb-superuser]
host=127.0.0.1
port=5435
user=postgres
dbname=postgres
```

## Installation

```bash
pipx install .
```

or

```bash
pipx install --editable .
```

## Initial Setup

After ensuring the requirements are met, run the following commands to set up the database:

```bash
partdb initdb
```

To load example data:
```bash
partdb loaddb --path  <path to example_data/>
partdb update_embeddings
```

To drop the database for a clean start:
```bash
partdb dropdb
```

## Usage
To add a new location:
```bash
partdb add <location name>
```

To add a new part:
```bash
partdb add <location name> <part description>
```

To list all parts:
```bash
partdb list
```

To list all parts at a location:
```bash
partdb list <location name>
```

To list all locations:
```bash
partdb list --locations
```

To search for a part using semantic (vector) search (requires OpenAI API call):
```bash
partdb search <part description>
```

To search for a part using full text search:
```bash
partdb search --full-text <search phrase>
```

To delete a part:
```bash
partdb delete --id <part id>
```

To delete a location:
```bash
partdb delete --location <location name>
```

To update the description of a part:
```bash
partdb update <part id> <new description>
```

To move a part to a new location:
```bash
partdb move <part id> <new location name>
```
