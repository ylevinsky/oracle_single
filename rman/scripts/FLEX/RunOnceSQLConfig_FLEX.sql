spool \\192.168.0.125\oracle\Backup_DB2\RMAN\scripts\RunOnceSQLScriopt.log
set echo on 

-- &1 is the backup target folder

--Setting SESSION defaults
ALTER SESSION SET NLS_LANGUAGE='AMERICAN' NLS_TERRITORY= 'AMERICA';
ALTER SESSION SET NLS_DATE_FORMAT='DD-MM-YYYY HH24:MI:SS';


--Setting DB parameters 
ALTER SYSTEM SET DB_RECOVERY_FILE_DEST_SIZE = 1000g SCOPE=BOTH SID='*';
ALTER SYSTEM SET DB_RECOVERY_FILE_DEST = '\\192.168.0.125\oracle\Backup_DB2\RMAN\backup_files' SCOPE=BOTH SID='*';
alter system set CONTROL_FILE_RECORD_KEEP_TIME = 14;

alter session set max_dump_file_size='20m';
alter system  set max_dump_file_size='20m';

ALTER DATABASE DISABLE BLOCK CHANGE TRACKING;
DELETE '\\192.168.0.125\oracle\Backup_DB2\RMAN\backup_files\rman_change_track_FLEX.f';
ALTER DATABASE ENABLE BLOCK CHANGE TRACKING USING FILE '\\192.168.0.125\oracle\Backup_DB2\RMAN\backup_files\rman_change_track_FLEX.f' REUSE;


SELECT * FROM V$RECOVERY_FILE_DEST;

select log_mode from v$database; 
show parameter db_recovery;
SELECT * FROM V$BLOCK_CHANGE_TRACKING;

select * from dual;

#---------------------Setting Archive mode on
archive log list;
show parameter db_recovery_file;

# Creating Datapump directory:

 CREATE OR REPLACE DIRECTORY MY_DATA_PUMP_DIRECTORY AS '&1\DATA_PUMP_BACKUP\Backup_Files';
 GRANT READ,WRITE ON DIRECTORY MY_DATA_PUMP_DIRECTORY TO system;
# -- shutdown immediate;

# startup is done in second script
/
exit