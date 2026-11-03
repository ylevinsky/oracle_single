# Daily routine rerun - 2026-09-15

- Request and scope: rerun the revised read-only daily Oracle routine after adding backup status and excluding schema-copy artifacts.
- Live aggregate: seven targets checked; zero clean, six with issues, and one failed.
- Backup status: HUN reported `errors_found` with 54 matching log records among up to 20 recent backup log files. DWH, DWH_CL, and RH were unverified because saved SSH usernames are missing. FLEX, PH, and Spain were unverified because `F:/Backup/Oracle/RMAN` was not found on those hosts.
- Connectivity: DWH Oracle check timed out with `DPY-6005`; its database state remains unverified.
- Capacity alerts: DWH_CL SYSTEM 8.97 percent; FLEX OFAKIM_TBS 11.42 percent and USERS 9.90 percent; PH SYSTEM 9.17 percent; RH SYSTEM 8.89 percent; Spain SPAIN_TBS 12.59 percent, SYSTEM 8.79 percent, and USERS 9.22 percent. DWH_CL UNDOTBS1, HUN HUNG_TBS, and HUN OFAKIM_TBS had no remaining AUTOEXTEND headroom.
- Scope verification: no `COPY_SCHEMA` or DBMS_DATAPUMP artifacts appeared in Spain job issues. No corrective action was taken.
