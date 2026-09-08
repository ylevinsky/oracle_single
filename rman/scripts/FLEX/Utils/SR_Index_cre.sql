

DECLARE 
	table_exists INT :=0;
	cmd varchar(255);

BEGIN 
	FOR C IN (SELECT USERNAME  FROM all_users
				WHERE ORACLE_MAINTAINED = 'N')
	LOOP 	
		table_exists:=0;
		
		SELECT COUNT(1)
		INTO table_exists
		FROM ALL_ALL_TABLES 
		WHERE OWNER = C.USERNAME
		AND TABLE_NAME = 'STEP_RESULT';
		
		IF table_exists > 0 THEN 
            cmd:='create index IX1_'||C.USERNAME||'_SR_Parents on '||C.USERNAME||'.Step_result(step_parent)';
			dbms_output.PUT_LINE(cmd) ;
            execute immediate cmd;
		END IF;
	
	END LOOP;
END;
/

