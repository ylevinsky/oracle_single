


-- &1 is the backup target folder

--Setting SESSION defaults
ALTER SESSION SET NLS_LANGUAGE='AMERICAN' NLS_TERRITORY= 'AMERICA';
ALTER SESSION SET NLS_DATE_FORMAT='DD-MM-YYYY HH24:MI:SS';


--Setting DB parameters 
ALTER SYSTEM SET DB_RECOVERY_FILE_DEST_SIZE = 200M SCOPE=BOTH SID='*';
ALTER SYSTEM SET DB_RECOVERY_FILE_DEST = '&1\RMAN\backup_files' SCOPE=BOTH SID='*';
alter system set CONTROL_FILE_RECORD_KEEP_TIME = 14;

ALTER DATABASE DISABLE BLOCK CHANGE TRACKING;
DELETE '&1\RMAN\backup_files\rman_change_track_HUN.f';
ALTER DATABASE ENABLE BLOCK CHANGE TRACKING USING FILE '&1\RMAN\backup_files\rman_change_track_HUN.f' REUSE;


SELECT * FROM V$RECOVERY_FILE_DEST;

select log_mode from v$database; 
show parameter db_recovery;
SELECT * FROM V$BLOCK_CHANGE_TRACKING;

select * from dual;

#---------------------Setting Archive mode on
archive log list;
show parameter db_recovery_file;

REM Creating Datapump directory:

CREATE OR REPLACE DIRECTORY my_data_pump_directory AS '&1\DATA_PUMP_BACKUP\Backup_Files';
GRANT READ,WRITE ON DIRECTORY my_data_pump_directory TO system;


select * from dual;



exit
