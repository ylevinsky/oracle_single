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


SET rman_backup_folder="F:\Oracle\Backup\RMAN\backup_files\ORCLSP\Full"
set RMAN_Weekly_CMD_FILE="F:\Oracle\Backup\RMAN\scripts\RMAN_Weekly_backup_script_ORCLSP.txt"
set sysUserAndPassword=sys/ProdE$$ence2023
set DbTnsName=ORCLSP
set SynCToY_Folder_Pair_Name="DuplicateOracleBackupFolder"


set StartTime=%dtStamp%

set logfile=F:\Oracle\Backup\RMAN\logs\Weekly_db_backup_log_%StartTime%.log
echo log to \logs\%logfile%


echo starting RMAN Backup at %dtStamp% >> %logfile%

echo using: rman TARGET %sysUserAndPassword% NOCATALOG cmdfile=%RMAN_Weekly_CMD_FILE%  

rman TARGET %sysUserAndPassword% NOCATALOG cmdfile=%RMAN_Weekly_CMD_FILE%  >> %logfile%


set backupEndTime=%dtStamp%
echo **************************************************************************************************************************************   >> %logfile% 
echo ***   Backup finished... at: %backupEndTime%  STARTED AT: %StartTime%
echo ***   Begin File Sync to Network Backup  time IS: %backupEndTime%                            ********************** >> %logfile% 
echo **************************************************************************************************************************************   >> %logfile% 

echo ************************************************************************************ >> %logfile%
echo ****   folder sync ended at:  %dtStamp%   started at: %backupEndTime%   ****** >> %logfile%
echo ****   all job  ended at: %dtStamp%       started at: %StartTime%        ***** >> %logfile% 