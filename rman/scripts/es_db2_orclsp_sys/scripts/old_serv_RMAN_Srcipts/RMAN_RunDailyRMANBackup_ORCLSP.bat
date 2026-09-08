REM Daily BackUp script , need to pre configure and run ONNCE the Run Once Batch file
REM @ECHO OFF
: Sets the proper date and time stamp with 24Hr Time for log file naming
: convention
SET HOUR=%time:~0,2%
echo sys_Date is:%DATE%
echo sys_time is:%TIME%
echo -%HOUR%-


SET dtStamp9=%date:~-4%-%date:~4,2%-%date:~7,2%_0%time:~1,1%-%time:~3,2%-%time:~6,2%
SET dtStamp24=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%HOUR:~0,1%" == " " (SET dtStamp=%dtStamp9%) else (SET dtStamp=%dtStamp24%)
ECHO %dtStamp%_time_is


SET rman_backup_folder="G:\Oracle\Backup\RMAN\backup_files\ORCLSP\Incremental" 
set RMAN_Daily_CMD_FILE="RMAN_Daily_backup_script_ORCLSP.txt"
set sysUserAndPassword=sys/ProdE$$ence2015
set DbTnsName=ORCLSP
set SynCToY_Folder_Pair_Name="DuplicateOracleBackupFolder"


set StartTime=%dtStamp%

set logfile=Daily_db_backup_log.log
echo starting log > %logfile%
echo log to %logfile%



echo starting RMAN Backup at %dtStamp% >> %logfile%

echo using: rman TARGET %sysUserAndPassword% cmdfile=%RMAN_Daily_CMD_FILE%  

rman TARGET %sysUserAndPassword%@%DbTnsName% cmdfile=%RMAN_Daily_CMD_FILE%  >> %logfile%


set backupEndTime=%TIME%
echo **************************************************************************************************************************************   >> %logfile% 
echo ***   Backup finished... at: %backupEndTime%  STARTED AT: %StartTime%
echo ***   Begin File Sync to Network Backup  time IS: %backupEndTime%                            ********************** >> %logfile% 
echo **************************************************************************************************************************************   >> %logfile% 

echo getting ready to sync folders.........>> %logfile% 

echo copy RMAN_CHANGE_TRACK_ORCLSP.F >> %logfile% 
copy /Y %rman_backup_folder%\RMAN_CHANGE_TRACK*.F %rman_backup_folder%\Backup_of_RMAN_CHANGE_TRACK_BACKUP_%dtstamp%.F  >> %logfile% 

echo copy current log file:     >> %logfile% 
copy /Y %logfile% logs\%logfile%_%StartTime%.log  




REM sync the Flash folder (master) with the Backup foler (slave) = usinc SyncToy tool(preInstalled)....   >> %logfile%
echo ***   Sync To Net Backup Folder Using command: C:\Program Files\SyncToy 2.1\SyncToyCmd.exe" -R %SynCToY_Folder_Pair_Nam%    ********************** >> %logfile% 

"C:\Program Files\SyncToy 2.1\SyncToyCmd.exe" -R %SynCToY_Folder_Pair_Name% >> %logfile%
 
echo ************************************************************************************ >> %logfile%
echo ****   folder sync ended at:  %TIME%   started at: %backupEndTime%   ****** >> %logfile%
echo ****   all job  ended at: %TIME%      started at: %StartTime%        ***** >> %logfile% 

echo **********************************************************************************************
echo *** check for errors in log :


findstr /m "Error" %logfile% 
if %errorlevel%==0 (
echo Err was Found! and logged >> %logfile% 
SmtpMailSender.exe ORCLSP-DB Error ; Error was found in Backup Log;  tzachar@essence-grp.com ; %logfile% 
) else (
echo No Err was found
)
