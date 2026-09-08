set ORACLE_SID=FLEX
set ORACLE_HOME=E:\Oracle\product\11.2.0\dbhome_1

set PATH=%ORACLE_HOME%\bin;%PATH%

SET l_PATH=F:\oracle\backup\Schaduled_Srcipts
SET log=%l_PATH%\Refresh_Statistics_Reports_log.log


SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-

SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)


cd %l_PATH%

echo ------start refresh statistics - %dtStamp% ------------------------------------------- >>  %log% 
sqlplus ATE_REPORTS/oracle@%ORACLE_SID% @Refresh_Statistics_Reports.sql >> %log%
SET HOUR=%time:~0,2%
SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)
echo End refresh statistics at: %dtStamp% ------------------------------------------- >>  %log% 
echo  "  "   >>  %log% 
