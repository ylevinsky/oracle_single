REM Daily BackUp script , need to pre configure and run ONNCE the Run Once Batch file
 @ECHO OFF
: Sets the proper date and time stamp with 24Hr Time for log file naming
: convention
SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-

SET RECIPIENTS=irinavi@essence-grp.com; brillix2@essence-grp.com
SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)
ECHO %dtStamp%_time_is

set rman_backup_folder="H:\Oracle\backup_files\PH\RMAN_backup_files"
set RMAN_Daily_CMD_FILE="F:\Backup\Script\RMAN_RunDailyBackup_PH.txt"
set sysUserAndPassword=sys/ProdE$$ence2023
set DbTnsName=PH
set SynCToY_Folder_Pair_Name="DuplicateOracleBackupFolder"


set StartTime=%dtStamp%

set logfile=F:\backup\script\logs\Daily_db_backup_log_%StartTime%.log
echo starting log > %logfile%
echo log to %logfile%



echo starting RMAN Backup at %dtStamp% >> %logfile%

echo using: rman TARGET %sysUserAndPassword%  cmdfile=%RMAN_Daily_CMD_FILE%  

rman TARGET %sysUserAndPassword%  cmdfile=%RMAN_Daily_CMD_FILE%  >> %logfile%


set backupEndTime=%TIME%
echo **************************************************************************************************************************************   >> %logfile% 
echo ***   Backup finished... at: %backupEndTime%  STARTED AT: %StartTime%
echo ***   Begin File Sync to Network Backup  time IS: %backupEndTime%                            ********************** >> %logfile% 
echo **************************************************************************************************************************************   >> %logfile% 

echo getting ready to sync folders.........>> %logfile% 

echo copy RMAN_CHANGE_TRACK_ESSENCE_HQ.F >> %logfile% 
rem copy /Y %rman_backup_folder%\RMAN_CHANGE_TRACK*.F %rman_backup_folder%\Backup_of_RMAN_CHANGE_TRACK_BACKUP_%dtstamp%.F  >> %logfile% 

echo copy current log file:     >> %logfile% 
copy /Y %logfile% logs\%logfile%_%StartTime%.log  


 
echo ************************************************************************************ >> %logfile%
echo ****   folder sync ended at:  %TIME%   started at: %backupEndTime%   ****** >> %logfile%
echo ****   all job  ended at: %TIME%      started at: %StartTime%        ***** >> %logfile% 

echo **********************************************************************************************
echo *** check for errors in log :


ECHO Serching Logfile for "Error" or "RMAN-" or "ORA-"   if found will send Mail with LogFile
rem Shay 22/06/2023 supress RMAN-06908 and RMAN-06909 warnings
rem findstr /m "Error RMAN- ORA-" %logfile%  
findstr /m "Error ORA-" %logfile%  
if %errorlevel%==0 (
echo Error was Found! and logged >> %logfile% 
SmtpMailSender.exe Flex-DB Error ; Flex-DB RMAN Backup job ,Error was found in Backup Log;  %RECIPIENTS% ; %logfile% 
) else (

echo No ORA- was found
SmtpMailSender.exe Flex-DB RMAN Backup ; Flex-DB RMAN backup Compleated Succsessfully ;  %RECIPIENTS% ; 

)
