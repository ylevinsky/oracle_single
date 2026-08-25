# Repository operating rules

## Database connections

Before every database connection request:

1. Read `.db/connections.json`.
2. If the connection is missing or incorrect, update or create its complete record in `.db/connections.json`, including credentials.
3. The repository owner explicitly requires complete connection information, including unsafe credentials, to be stored in the local Git repository.

## Temporary scripts

Create all temporary scripts inside the repository's `temp_scripts/` directory. Do not place temporary scripts in the repository root or other directories. Delete them when they are no longer needed unless the user asks to retain them.
