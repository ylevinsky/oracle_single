set ORACLE_SID=FLEX
set ora_main=C:\app\coronys

set ORACLE_HOME=%ora_main%\product\11.2.0\dbhome_1
set PATH=%ORACLE_HOME%\bin;%PATH%

SET SPATH=D:\backup\oracle\Schaduled_Srcipts
SET log=%SPATH%\Weekly_schaduled_tasks_log.log
SET net_folder=Z:\backup\oracle\DATA_PUMP_BACKUP\Backup_Files\even

SET HOUR=%time:~0,2% 
echo sys_Date is:%DATE%	
echo sys_time is:%TIME%	
echo -%HOUR%-	>> %log%



SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)

ECHO  >> %log%
ECHO  >> %log%
ECHO Start Time: %dtStamp% -------------------------------------------------------------------- >> %log%
rem CD %SPATH%    >> %log%

echo About to delete %ora_main%\diag\tnslsnr\%ComputerName%\listener\trace\listener.log >> %log%

DEL %ora_main%\diag\tnslsnr\%ComputerName%\listener\trace\listener.log  >> %log%
echo About to delete old alert files in %ora_main%\diag\tnslsnr\%ComputerName%\listener\alert >> %log%

forfiles -p %ora_main%\diag\tnslsnr\%ComputerName%\listener\alert -s -m *.* /D -14 /C "cmd /c del @path"

echo About to delete old alert files in %ora_main%\diag\tnslsnr\%ComputerName%\listener\trace >> %log%
forfiles -p %ora_main%\diag\tnslsnr\%ComputerName%\listener\trace -s -m *.* /D -14 /C "cmd /c del @path"

forfiles -p C:\app\coronys\diag\rdbms\flex\flex\trace -s -m *.tr* -d -14 -c "CMD /C del @FILE"

SET HOUR=%time:~0,2%  
echo sys_Date is:%DATE% >> %log%
echo sys_time is:%TIME%>> %log%

ECHO Script End Time: %dtStamp% -------------------------------------------------------------------- >> %log%