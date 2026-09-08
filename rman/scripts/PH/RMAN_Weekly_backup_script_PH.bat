REM Weekly BackUp script , need to pre configure and run ONNCE the Run Once Batch file
REM @ECHO OFF
: Sets the proper date and time stamp with 24Hr Time for log file naming
: convention
SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-

SET %RECIPIENTS=irinavi@essence-grp.com
SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)
ECHO %dtStamp%_time_is

SET rman_backup_folder="H:\Oracle\backup_files\PH\RMAN_backup_files"
set RMAN_Weekly_CMD_FILE="F:\Backup\Script\RMAN_Weekly_backup_script_PH.txt"
set sysUserAndPassword=sys/ProdE$$ence2023
set DbTnsName=PH
set SynCToY_Folder_Pair_Name="DuplicateOracleBackupFolder"


set StartTime=%dtStamp%

set logfile=F:\backup\script\logs\Weeky_db_backup_log_%StartTime%.log
echo starting log > %logfile%
echo log to %logfile%



echo starting RMAN Backup at %dtStamp% >> %logfile%

echo using: rman TARGET %sysUserAndPassword% NOCATALOG cmdfile=%RMAN_Weekly_CMD_FILE% >> %logfile%

rman TARGET %sysUserAndPassword% NOCATALOG cmdfile=%RMAN_Weekly_CMD_FILE%  >> %logfile%

rem rman TARGET %sysUserAndPassword%@%DbTnsName% NOCATALOG cmdfile=%RMAN_Weekly_CMD_FILE%  >> %logfile%


set backupEndTime=%TIME%
echo **************************************************************************************************************************************   >> %logfile% 
echo ***   Backup finished... at: %backupEndTime%  STARTED AT: %StartTime%
echo ***   Begin File Sync to Network Backup  time IS: %backupEndTime%                            ********************** >> %logfile% 
echo **************************************************************************************************************************************   >> %logfile% 

echo getting ready to sync folders.........>> %logfile% 

echo copy RMAN_CHANGE_TRACK_ESSENCE_HQ.F >> %logfile% 
rem copy /Y %rman_backup_folder%\RMAN_CHANGE_TRACK*.F %rman_backup_folder%\Backup_of_RMAN_CHANGE_TRACK_BACKUP_%dtstamp%.F  >> %logfile% 

echo copy current log file:     >> %logfile% 
rem copy /Y %logfile% logs\%logfile%_%StartTime%.log  

 
echo ************************************************************************************ >> %logfile%
echo ****   folder sync ended at:  %TIME%   started at: %backupEndTime%   ****** >> %logfile%
echo ****   all job  ended at: %TIME%      started at: %StartTime%        ***** >> %logfile% 

echo **********************************************************************************************
echo *** check for errors in log :


findstr /m "Error" %logfile% 
if %errorlevel%==0 (
echo Err was Found! and logged >> %logfile% 
SmtpMailSender.exe Flex-DB Error ; Error was found in Backup Log; %RECIPIENTS%; %logfile% 
) else (

findstr /m "ORA-" %logfile% 
if %errorlevel%==0 (
echo Err was Found! and logged >> %logfile% 
SmtpMailSender.exe WEEKLY Flex-DB BACKUP Error ; Error was found in WEEKLY Backup Log;  %RECIPIENTS%; %logfile% 
) else (
echo No Err was found
)

)
