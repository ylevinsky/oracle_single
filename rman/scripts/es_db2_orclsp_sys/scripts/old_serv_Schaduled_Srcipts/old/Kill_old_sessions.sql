DECLARE 
  CURSOR kill_sessions_cur
   IS
      SELECT s.SID, s.serial#
        FROM v$session s
      WHERE     last_call_et > 660
       and PROGRAM IN ('TSExec.exe')
       AND username IS NOT NULL
       AND username NOT IN  ('SYS',
                    'SYSTEM',
                    'DBSNMP',
                    'TSMSYS',
                    'OUTLN',
                    'EXFSYS',
                    'ORDSYS',
                    'WMSYS',
                    'XDB',
                    'MDSYS'
                   )
       AND status = 'INACTIVE';
       

   v_cmd   VARCHAR2 (100);
BEGIN
   FOR kill_sessions_rec IN kill_sessions_cur
   LOOP
      v_cmd :=
            'Alter system kill session '''
         || kill_sessions_rec.SID
         || ','
         || kill_sessions_rec.serial#
         || ''' immediate';

      EXECUTE IMMEDIATE v_cmd;
   END LOOP;
END;
/
exit