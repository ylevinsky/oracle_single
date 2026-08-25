# Available MCP tools: myoracle

The repository-scoped `myoracle` MCP server provides these seven tools. Database
tools use saved records in `.db/connections.json` and connect directly without
requiring a confirmation token.

## connections_list

Lists saved Oracle connection names without connecting to a database.

## prepare_connection

Reads and returns the complete saved connection details without opening a
database connection. This includes the configured connection metadata and
stored credential field.

## list_schemas

Connects to a selected saved Oracle connection and returns schema names from
`DBA_USERS`, ordered by username.

## list_custom_jobs

Connects to a selected saved Oracle connection and lists Scheduler and legacy
jobs owned by users where `DBA_USERS.ORACLE_MAINTAINED = 'N'`.

## inspect_saved_database_space

Connects to a selected saved Oracle connection and reports allocated bytes,
maximum configured bytes, free bytes, free percentage, and AUTOEXTEND file
counts for online permanent and UNDO tablespaces.

## list_top_full_scan_queries

Ranks shared-pool SQL from non-Oracle-maintained parsing schemas whose child
cursor plans contain `TABLE ACCESS FULL`. Results include physical reads,
buffer gets, executions, elapsed time, SQL text, and scanned objects.

## inspect_sql_index_context

Inspects a SQL ID in `V$SQL_PLAN` and returns plan predicates, referenced
objects, table statistics, relevant column statistics, and existing indexes.
