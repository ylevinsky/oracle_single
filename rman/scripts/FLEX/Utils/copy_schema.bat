
 @echo off 

if [%1]==[] goto :usage
if [%2]==[] goto :usage

set from_schema=%1
set to_schema=%2

rem : Sets the proper date and time stamp with 24Hr Time for log file naming
rem : convention
SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-

SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)
ECHO %dtStamp%_time_is

SET dumpfile=expdp_%from_schema%_%dtStamp%.dmp
SET logfile=%from_schema%_%dtStamp%.log
set "dumpfile=%dumpfile:/=-%"
set "logfile=%logfile:/=-%"
echo %dumpfile%

REM "expdp  DIRECTORY=DP_DIR dumpfile=IPDEP_SYSEM_14012024.dmp SCHEMAS=IPDEP_SYSEM logfile=remap_idep_sysem.log"

set oracle_bin=C:\app\oracle\product\19.0.0\dbhome_1\bin\
SET dba_user=shay
SET dba_pass=shay
SET uaer_pass=oracle
SET sqlplus_cmd=%oracle_bin%\sqlplus.exe

set exp_cmd=%oracle_bin%\expdp.exe %dba_user%/%dba_pass% DIRECTORY=DP_DIR dumpfile=%dumpfile% SCHEMAS=%from_schema%  logfile=expdp_%logfile% CONTENT=METADATA_ONLY
echo Exporting source schema %from_schema% to file 
echo %exp_cmd%
%exp_cmd%

set imp_cmd=%oracle_bin%\impdp %dba_user%/%dba_pass% DIRECTORY=DP_DIR dumpfile=%dumpfile% REMAP_SCHEMA=%from_schema%:%to_schema%  logfile=impdp_%logfile%
echo Importing schema %to_schema% from file 
echo %imp_cmd%
%imp_cmd%

ECHO ALTER USER  %to_schema% IDENTIFIED BY %uaer_pass%; > cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.MEAS_NUMERICLIMIT TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_MEAS_NUMERICLIMIT FOR %to_schema%.MEAS_NUMERICLIMIT; >> cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.STEP_MSGPOPUP TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_STEP_MSGPOPUP FOR %to_schema%.STEP_MSGPOPUP; >> cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.STEP_PASSFAIL TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_STEP_PASSFAIL FOR %to_schema%.STEP_PASSFAIL; >> cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.STEP_RESULT TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_STEP_RESULT FOR %to_schema%.STEP_RESULT; >> cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.STEP_STRINGVALUE TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_STEP_STRINGVALUE FOR %to_schema%.STEP_STRINGVALUE; >> cmd.sql
ECHO / >> cmd.sql
echo GRANT SELECT ON %to_schema%.UUT_RESULT TO EREPORTS; >> cmd.sql
ECHO / >> cmd.sql
ECHO CREATE SYNONYM EREPORTS.%to_schema%_UUT_RESULT FOR %to_schema%.UUT_RESULT; >> cmd.sql
ECHO / >> cmd.sql
ECHO exit; >> cmd.sql
ECHO / >> cmd.sql


%sqlplus_cmd% %dba_user%/%dba_pass% @cmd.sql

delete cmd.sql
echo "Schema created successfully"
exit /b

:usage 
echo usage: copy_schema from_schema to_schema 