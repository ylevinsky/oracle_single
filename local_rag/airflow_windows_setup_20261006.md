# Airflow on native Windows setup - 2026-10-06

## Request and scope
Run Airflow natively on Windows with Oracle and Postgres providers, admin
credentials in env + Windows Credential Manager, latest stable on Python 3.14,
metadata DB on local PostgreSQL 18 instead of sqlite, UI in external browser.

## Environment
- Python 3.11.9 (`C:\Users\brillix\AppData\Local\Programs\Python\Python311`)
  initially hosted Airflow 2.9.3; later uninstalled.
- Python 3.14.6 (`C:\Users\brillix\AppData\Local\Python\pythoncore-3.14-64`)
  hosts Airflow 3.3.2 (latest stable per PyPI, requires-python `!=3.15,>=3.10`).
- PostgreSQL 18 service `postgresql-x64-18`, database `airflow`, role `airflow`.
- Airflow 2.9.3 requires-python `<3.13,~=3.8`, so Python 3.14 needs Airflow 3.x.

## Installed on Python 3.14
- `apache-airflow==3.3.2` with constraints
  `https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.14.txt`
- Providers: `apache-airflow-providers-oracle 4.6.3`,
  `apache-airflow-providers-postgres 7.0.2`, `oracledb 26.0.0`,
  `psycopg2-binary 2.9.13`, plus `psycopg`/`psycopg-binary`/`asyncpg`.
- `C:\...\pythoncore-3.14-64\Scripts` added to User PATH so `airflow` resolves.

## Windows patches (site-packages, lost on reinstall)
- `airflow/settings.py` (2.9.3 only): accept `sqlite:///<Drive>:/...`; 3.x
  removed that check.
- `airflow/_shared/observability/metrics/stats.py` and
  `airflow/sdk/_shared/observability/metrics/stats.py`: guard
  `os.register_at_fork` with `hasattr` (POSIX-only).
- `airflow/cli/commands/daemon_utils.py`: guard `signal.SIGQUIT` (missing).
- Shims added to 3.14 site-packages: `fcntl.py` (no-op flock),
  `pwd.py`, `resource.py` (stubs for `python-daemon` import chain).
- `airflow/www/app.py` (2.9.3 only): accept Windows drive sqlite URLs.

## Postgres metadata DB
- `AIRFLOW_HOME=C:/Users/brillix/airflow314`
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg://airflow:PASSWORD@localhost:5432/airflow`
- DB password in env `AIRFLOW_DB_PASSWORD` + Credential Manager `AIRFLOW_POSTGRES`.
- `airflow db migrate` works natively; `airflow standalone` hangs on Windows
  at the migrate step, and `airflow webserver`/`scheduler` pull gunicorn/daemon
  paths that do not work — serve the UI with `airflow api-server --port 8080`
  (uvicorn), which runs fine on Windows.

## Auth (Airflow 3)
- No `airflow users create`; SimpleAuthManager reads JSON passwords file.
- `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE` points at
  `C:/Users/brillix/airflow314/simple_auth_manager_passwords.json`
  containing `{"admin": "admin"}`.
- Admin env `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD` + Credential
  Manager `AIRFLOW_ADMIN` kept in sync (currently admin/admin, dev only).

## UI
- Served at `http://127.0.0.1:8080`, opened in external browser per preference
  (links go to the system browser, not the IDE tab).
- API server only; scheduler/dag-processor not started, so nothing executes
  on schedule yet.
- Old 2.9.3 home `C:/Users/brillix/airflow` left on disk as backup.

## Dead ends hit the same day
- `wsl --install` for Ubuntu/Ubuntu-26.04/Ubuntu-24.04/Debian all fail with
  `TRUST_E_BAD_DIGEST` (stale feed hashes); `wsl --update` fails with
  `0x80072f7d` secure-channel error. Manual import path not completed.
- Airflow 3.3.2 `standalone` spawns `airflow` subcommands requiring PATH fix,
  then stalls; use `api-server` directly.
