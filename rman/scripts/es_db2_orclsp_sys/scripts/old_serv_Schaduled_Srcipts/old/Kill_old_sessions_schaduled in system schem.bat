
SET SPATH=F:\Oracle\Backup\Schaduled_Srcipts
SET log=%SPATH%\Kill_old_sessions_log.log


SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-



SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)

ECHO  >> %log%
ECHO  >> %log%
ECHO Start Time: %dtStamp% -------------------------------------------------------------------- >> %log%
rem CD %SPATH%    >> %log%

sqlplus sys/ProdE$$ence2015 as sysdba @Kill_old_sessions.sql >> %log%


ECHO Script ended ---------------------------------------------------------->> %log%