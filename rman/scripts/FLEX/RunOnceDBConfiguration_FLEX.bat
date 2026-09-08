SET RECOVERY_FOLDER=\\192.168.0.125\Oracle\Backup_DB2
set ORACLE_SID=flex_19
set logFile=RunOnceDBConfiguration_FLEX.log

REM Verify existing backup folders
MD %RECOVERY_FOLDER%
MD %RECOVERY_FOLDER%\RMAN\backup_files
MD %RECOVERY_FOLDER%\DATA_PUMP_BACKUP\Backup_Files


sqlplus system/ProdE$$ence2015@flex_19 as sysdba @RunOnceSQLConfig_FLEX.sql %RECOVERY_FOLDER%   >>  %logFile%


REM Startup after shutdown
sqlplus system/ProdE$$ence2015@flex_19 as sysdba @RunOnceSQLConfig_FLEX_continue_Startup.sql >>  %logFile%


REM rman TARGET sys/ProdE$$ence2015@flex_19 NOCATALOG cmdfile="RunOnceRMANScript_FLEX.txt '%RECOVERY_FOLDER%'"
rman TARGET sys/ProdE$$ence2015 NOCATALOG cmdfile="RunOnceRMANScript_FLEX.txt '%RECOVERY_FOLDER%'"          >>  %logFile%

pause