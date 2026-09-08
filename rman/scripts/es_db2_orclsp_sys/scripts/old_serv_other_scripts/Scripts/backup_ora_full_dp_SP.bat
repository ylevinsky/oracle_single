@echo on
set backup_folder=G:\Oracle\Backup\DATA_PUMP_BACKUP\Backup_Files
set logfile=%backup_folder%\full_dp_backup_job_log.log


for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "YY=%dt:~2,2%" & set "YYYY=%dt:~0,4%" & set "MM=%dt:~4,2%" & set "DD=%dt:~6,2%"
set "HH=%dt:~8,2%" & set "Min=%dt:~10,2%" & set "Sec=%dt:~12,2%"
set daytime=%DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec%

set fullstamp="full_expdp_ora_backup_SP_%daytime%"
rem set fullstamp=test2

echo cleaning old .dmp files if exists	
DEL /Q /F %backup_folder%\*.dmp  
DEL /Q /F %backup_folder%\*.log 

echo --------------------------  ------------------------------  > %logfile%
echo starting fullstamp: %fullstamp%              >>   %logfile%



echo --starting backup             >>   %logfile%

set start="%DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec%"
expdp system/ProdE$$ence2015@ORCLSP full=y directory=my_data_pump_directory logfile=%fullstamp%.log dumpfile=%fullstamp%.dmp 

echo --backup started at: %start%
echo --backup ended at  : %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec%              >>   %logfile%

echo -- delete old backup   >>   %logfile%		

DEL /Q /S /F %backup_folder%\Zipped_DataPump_previus  >>   %logfile%
MD %backup_folder%\Zipped_DataPump_previus
rem pause
echo --moving last backup to Zipped_DataPump_previus    >>   %logfile%
rem CD %backup_folder%
move /Y %backup_folder%\Zipped_DataPump\*.* %backup_folder%\Zipped_DataPump_previus  >>   %logfile%
rem pause

echo --Start Compress 7zip file at  %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec% 	  >>   %logfile%
MD %backup_folder%\Zipped_DataPump
DEL /Q /S /F %backup_folder%\Zipped_DataPump\*.*
set source=%backup_folder%\%fullstamp%.*
set dest=%backup_folder%\Zipped_DataPump\7zip_%fullstamp%.7z
echo source = %source%
echo --start "C:\Program Files\7-Zip\7z.exe" a -t7z -mx3 %dest% %source% -aoa
"C:\Program Files\7-Zip\7z.exe" a -t7z -mx3 %dest% %source% -aoa
echo --End Copy Compressed 7zip file at %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec% 	  >>   %logfile%


rem Copy Configurations
set conf_folder=%backup_folder%\db_configuration
MD %conf_folder%
echo --Start Copy DataBase configuration files to the %conf_folder%  folder for network backup


SET source=E:\Oracle\oradata\orclsp\CONTROL01.CTL
echo control file 1 - xcopy /Y /E %source% %conf_folder%
xcopy /Y %source% %conf_folder% 

SET source=E:\Oracle\fast_recovery_area\orclsp\control02.ctl
echo control file 2 - xcopy /Y /E %source% %conf_folder%
xcopy /Y %source% %conf_folder% 

SET source=E:\Oracle\product\11.2.0\dbhome_1\database\*.ORA
echo oracle Database definition folder - xcopy /Y /E %source% %conf_folder%
xcopy /Y %source%  %conf_folder%


SET source=E:\Oracle\product\11.2.0\dbhome_1\NETWORK\ADMIN\*.ORA
echo control file 1 - xcopy /Y /E %source% %conf_folder%
xcopy /Y %source% %conf_folder% 

echo Copy Configuration Files to  %conf_folder% Ended at %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec% 	  >>   %logfile%

set source=%conf_folder%
set dest=%backup_folder%\Zipped_DataPump\7zip_%fullstamp%.7z 
rem Add configuration to archive
"C:\Program Files\7-Zip\7z.exe" a -t7z -mx3 %dest% %source% 


echo DataPump Backup job ended at %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec% 	  >>   %logfile%

echo Add job log to archive  at %DD%-%MM%-%YYYY%_%HH%-%Min%-%Sec% 	  >>   %logfile%
set source=%logfile%
set dest=%backup_folder%\Zipped_DataPump\7zip_%fullstamp%.7z 
"C:\Program Files\7-Zip\7z.exe" a -t7z -mx3 %dest% %source% 
