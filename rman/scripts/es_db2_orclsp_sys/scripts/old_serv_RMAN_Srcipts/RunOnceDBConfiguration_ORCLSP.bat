SET RECOVERY_FOLDER=G:\Oracle\Backup
set ORACLE_SID=ORCLSP
set logFile=RunOnceDBConfiguration_ORCLSP.log

REM Verify existing backup folders
MD %RECOVERY_FOLDER%
MD %RECOVERY_FOLDER%\RMAN\backup_files
MD %RECOVERY_FOLDER%\DATA_PUMP_BACKUP\Backup_Files


sqlplus sys/ProdE$$ence2015@ORCLSP as sysdba @RunOnceSQLConfig_ORCLSP.sql %RECOVERY_FOLDER%   >>  %logFile%


REM Startup after shutdown
sqlplus sys/ProdE$$ence2015 as sysdba @RunOnceSQLConfig_ORCLSP_continue_Startup.sql >>  %logFile%


REM rman TARGET sys/ProdE$$ence2015 NOCATALOG cmdfile="RunOnceRMANScript_ORCLSP.txt '%RECOVERY_FOLDER%'"
rman TARGET sys/ProdE$$ence2015 NOCATALOG cmdfile="RunOnceRMANScript_ORCLSP.txt '%RECOVERY_FOLDER%'"          >>  %logFile%

pause