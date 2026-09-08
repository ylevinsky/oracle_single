SET RECOVERY_FOLDER=G:\Backup\Oracle
set ORACLE_SID=HUN
set logFile=RunOnceDBConfiguration_HUN.log

REM Verify existing backup folders
MD %RECOVERY_FOLDER%
MD %RECOVERY_FOLDER%\RMAN\backup_files
MD %RECOVERY_FOLDER%\DATA_PUMP_BACKUP\Backup_Files
CD %RECOVERY_FOLDER%\RMAN\SCRIPTS

echo ---------------------------Starting script   ---------------------  > %logFile%
sqlplus sys/ProdE$$ence2015@HUN as sysdba @RunOnceSQLConfig_HUN.sql %RECOVERY_FOLDER%   >>  %logFile%

ping -n 5 127.0.0.1 

Echo -----------Please restart the oracle service and then run RunOnceDBConfiguration_HUN_continue.bat  

ping -n 5 127.0.0.1 
REM rman TARGET sys/ProdE$$ence2015 NOCATALOG cmdfile="RunOnceRMANScript_HUN.txt '%RECOVERY_FOLDER%'"
rman TARGET sys/ProdE$$ence2015 NOCATALOG cmdfile="RunOnceRMANScript_HUN.txt '%RECOVERY_FOLDER%'"  >>  %logFile%        >>  %logFile%

pause

