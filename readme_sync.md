# FLEX to DWH sync

Checked 2026-10-13.

## What runs

The sync is the Oracle Scheduler job `SYNC_USER.FLEX_DATA_REFRESH` on the warehouse. It runs daily at 00:30 and calls `SYNC_USER.FLEX_REFRESH.REFRESH_ALL`.

Production DWH (`esi-wh-fl.esi-fl-il.com`, service `flexdwh.ESI-FL-IL.COM`) timed out, so the job definition, the table list, and the destination sizes below were read from the warehouse clone `DWH_CL` (`of-oracle.essencesecurity.com`, SID `dwhcl`). On that clone the job is enabled. Its last run started 2026-10-13 00:30 and succeeded in 42 minutes 45 seconds. The next run is 2026-10-14 00:30. Lifetime totals on the clone are 471 runs and 5 failures.

FLEX (`es-db2-fl.esi-fl-il.com`, SID `FLEX`) has no job that pushes data to the warehouse.

## How one schema is refreshed

`REFRESH_ALL` walks `SYNC_USER.SYNC_SCHEMAS` (89 schemas) and calls `REFRESH_SCHEMA` for each one.

1. Fast-refresh the demand materialized views `SYNC_USER.<SCHEMA>_UUT_RESULT_REMOTE_MV` and `SYNC_USER.<SCHEMA>_STEP_RESULT_REMOTE_MV`. Both masters are on FLEX through the public database link `PUBLIC.FLEX.ESI-FL-IL.COM` (connected as `SHAY`). There are 89 `UUT_RESULT` views and 89 `STEP_RESULT` views.
2. Insert FLEX `UUT_RESULT` rows that are missing from the local `<SCHEMA>.UUT_RESULT` table. Rows whose source `START_DATE_TIME` is newer are identified, and a local delete of those ids is built, but that delete is not executed.
3. Insert missing `STEP_RESULT` rows the same way.
4. For every local table in that schema that has a `STEP_RESULT` column, insert the child rows from `<SCHEMA>.<TABLE>@PUBLIC.FLEX.ESI-FL-IL.COM` whose `STEP_RESULT` id was just added. The job log names these tables `MEAS_IVI_SINGLEPOINT`, `MEAS_IVI_WAVE`, `MEAS_IVI_WAVEPAIR`, `MEAS_NUMERICLIMIT`, `STEP_CALLEXE`, `STEP_MSGPOPUP`, `STEP_PASSFAIL`, `STEP_PROPERTYLOADER`, `STEP_SEQCALL`, and `STEP_STRINGVALUE`.

The sync does not delete business rows on FLEX. A fast refresh can purge already-applied rows from the FLEX materialized-view logs. Last night those log purges removed 0 rows.

Three schemas still have a failed status stored in `SYNC_SCHEMAS` from an older run: `EPA` and `HC_SYSTEM` (`ORA-12008`, 2026-05-19) and `SOLITION_TECH` (`ORA-12170`, 2026-02-06). The other 86 schemas are marked successful. Those flags were not rewritten by a later success, so they are not by themselves the result of the 2026-10-13 run.

## Are all FLEX tables synced?

No. FLEX has 2,832 tables owned by accounts that Oracle does not maintain. 1,068 of them are sync targets on `DWH_CL`. The other 1,318, after materialized-view logs and internal tables are left out, are listed in `not_synced.md`.

Twelve FLEX schemas have a `UUT_RESULT` table and are not in `SYNC_SCHEMAS`: `FACTORY_RESTORE`, `FOG_STG`, `FOTA`, `OPDI2`, `SPB`, `TEST2_HC2`, `TEST_FOG`, `TEST_HC_FOG`, `TEST_HC_FOG2`, `TEST_SK5`, `VF3P_TST`, and `WERP`.

Schemas with no synced table: `ALEXEY`, `ALONSPIEGEL`, `ATE`, `ATE_PRODUCTS`, `ATE_REPORTS`, `ATE_RESULTS`, `CORONYS_LOGS`, `ENG_REPORTS`, `EREPORTS`, `ESSENCE_MANAGER`, `FACTORY_RESTORE`, `FOG_STG`, `FOTA`, `MGLS_TEST`, `OOBA_QC`, `OOBA_SAMPLING`, `OPDI2`, `SERIAL_NUMBER`, `SHAY`, `SHIPMENT_GLOBAL`, `SHIPPING`, `SPB`, `TEST2_HC2`, `TEST_CP`, `TEST_FOG`, `TEST_HC_FOG`, `TEST_HC_FOG2`, `TEST_SK5`, `TOAD_EXECUTIONS_PLAN`, `VERSION_MANAGEMENT`, `VF3P_TST`, `WERP`.

## Size comparison

Sizes are table-segment megabytes from `DBA_SEGMENTS` (`SEGMENT_TYPE = 'TABLE'`). Index and LOB segments are not included, and allocated space is not the same as row count. A destination larger than the source can be free space left in the segment, or rows that were inserted again because the local update-delete is not executed.

Synced tables: FLEX 649,542.3 MB, DWH_CL 644,874.3 MB, difference -4,668.0 MB.
Tables that are not synced occupy 128,546.6 MB on FLEX and have no matching sync target on DWH_CL.

### Synced tables whose segment size differs by more than 10 percent or 100 MB

Row counts are `DBA_TABLES.NUM_ROWS`, except the four FLEX `MGLSP` tables and both `SYSTEM_IOT_2.STEP_SEQCALL` counts, which had no statistics and were counted directly. The only date column on these tables is `START_DATE_TIME`, and only `UUT_RESULT` has it. Its minimum and maximum are the low and high values stored in column statistics.

| Schema.table | FLEX MB | DWH_CL MB | DWH_CL minus FLEX | FLEX rows | DWH_CL rows | FLEX min | FLEX max | DWH_CL min | DWH_CL max | FLEX deletion procedure |
|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| `SK2.STEP_RESULT` | 3,968.0 | 14,694.0 | 10,726.0 | 34,175,055 | 132,591,702 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLSP.STEP_SEQCALL` | 8,220.0 | 888.0 | -7,332.0 | 97,956,526 | 10,183,191 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLS.MEAS_NUMERICLIMIT` | 8,640.0 | 1,795.0 | -6,845.0 | 61,292,230 | 42,768,405 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLSP.MEAS_NUMERICLIMIT` | 5,815.0 | 632.0 | -5,183.0 | 143,221,511 | 15,434,610 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SK2.STEP_SEQCALL` | 944.0 | 5,120.0 | 4,176.0 | 12,348,640 | 8,011,490 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SK2.MEAS_NUMERICLIMIT` | 832.0 | 4,608.0 | 3,776.0 | 20,122,183 | 112,674,922 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLS.STEP_STRINGVALUE` | 3,008.0 | 536.0 | -2,472.0 | 14,242,090 | 8,274,275 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `HC_PROG.STEP_RESULT` | 6,047.0 | 7,614.0 | 1,567.0 | 55,554,903 | 73,007,143 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLSP.STEP_STRINGVALUE` | 1,691.0 | 219.0 | -1,472.0 | 25,686,192 | 2,552,702 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `HC_SYSTEM.STEP_RESULT` | 5,236.0 | 6,432.0 | 1,196.0 | 49,714,982 | 60,913,028 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SYSTEM_ATE_2.STEP_RESULT` | 39,790.0 | 38,684.0 | -1,106.0 | 359,127,129 | 362,765,831 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `DLCK.STEP_RESULT` | 520.0 | 1,475.0 | 955.0 | 4,454,703 | 13,562,933 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SK2.STEP_STRINGVALUE` | 216.0 | 998.0 | 782.0 | 2,684,275 | 1,803,910 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLS.STEP_SEQCALL` | 13,168.0 | 12,453.0 | -715.0 | 48,661,380 | 31,241,042 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SYSTEM_ATE_2.STEP_SEQCALL` | 14,381.0 | 13,669.0 | -712.0 | 28,423,640 | 28,423,640 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `EPA.STEP_RESULT` | 11,851.0 | 11,190.0 | -661.0 | 105,896,385 | 106,869,469 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SYSTEM_ATE_2.STEP_STRINGVALUE` | 4,162.0 | 3,904.0 | -258.0 | 9,899,330 | 9,899,330 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SYSTEM_ATE_2.MEAS_NUMERICLIMIT` | 5,251.0 | 5,056.0 | -195.0 | 17,979,010 | 17,979,010 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SK2.UUT_RESULT` | 41.0 | 224.0 | 183.0 | 184,177 | 1,000,458 | 2025-06-26 09:25:26 | 2026-09-16 13:55:47 | 2021-01-25 00:03:19 | 2026-08-11 03:44:47 | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `EPA.STEP_STRINGVALUE` | 1,709.0 | 1,600.0 | -109.0 | 2,066,200 | 2,066,200 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `EPA.MEAS_NUMERICLIMIT` | 2,446.0 | 2,339.0 | -107.0 | 3,971,200 | 3,971,200 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLS.STEP_PASSFAIL` | 23.0 | 5.0 | -18.0 | 285,550 | 175,127 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLSP.STEP_PASSFAIL` | 15.0 | 2.0 | -13.0 | 576,910 | 60,322 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `DLCK.UUT_RESULT` | 7.0 | 19.0 | 12.0 | 27,810 | 78,838 | 2025-08-01 00:02:46 | 2026-05-07 12:22:56 | 2022-08-01 01:13:59 | 2026-05-03 14:19:34 | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SYSTEM_IOT_2.STEP_SEQCALL` | 72.0 | 64.0 | -8.0 | 680,429 | 672,280 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `SK2.STEP_PASSFAIL` | 0.1 | 2.0 | 1.9 | 18 | 51,110 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |
| `MGLM.STEP_STRINGVALUE` | 4.0 | 5.0 | 1.0 | 4,213,560 | 4,213,560 | | | | | `ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` |

The largest shortfall is in the `MGLS` and `MGLSP` child tables (`MEAS_NUMERICLIMIT`, `STEP_SEQCALL`, `STEP_STRINGVALUE`): the warehouse copies are several gigabytes smaller than FLEX. `SK2.STEP_RESULT`, `SK2.STEP_SEQCALL`, and `SK2.MEAS_NUMERICLIMIT` are larger on the warehouse than on FLEX. Several `MGLS`, `EPA`, and `SYSTEM_ATE_2` child-table statistics were last gathered in 2021. Every schema in this table has the seven result tables the deletion procedure selects, and every table name in this table is one of the tables that procedure deletes.

## Data deletion Flex procedure

`ATE_RESULTS.IMP_EXP_RESULTS.DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD` is the FLEX procedure that deletes old rows from `SK2.UUT_RESULT` and `DLCK.UUT_RESULT`. It takes one argument, `LEAVE_LAST_MONTHES`.

It reads the site prefix and cloud database link from `ATE_REPORTS.GENERAL`, then calls `Get_ate_schemas_from_site`. That function returns every schema that has all seven tables `MEAS_NUMERICLIMIT`, `STEP_PASSFAIL`, `STEP_RESULT`, `STEP_STRINGVALUE`, `UUT_CONFIGURATIONS`, `UUT_RESULT`, and `UUT_TYPES`. Both `SK2` and `DLCK` match, as do the other schemas in the size-difference table above: `EPA`, `HC_PROG`, `HC_SYSTEM`, `MGLM`, `MGLS`, `MGLSP`, `SYSTEM_ATE_2`, and `SYSTEM_IOT_2`.

For each schema it finds the last result id still inside the retention window and calls `DEL_RES_UP_TO_RES_ID`. That function deletes older child rows, then `STEP_RESULT`, then:

`DELETE <schema>.UUT_RESULT WHERE ID IN (...)`

The child tables it deletes are `MEAS_NUMERICLIMIT`, `STEP_STRINGVALUE`, `STEP_SEQCALL`, `STEP_PASSFAIL`, `STEP_MSGPOPUP`, `STEP_CALLEXE`, `STEP_PROPERTYLOADER`, `MEAS_IVI_SINGLEPOINT`, `MEAS_IVI_WAVE`, and `MEAS_IVI_WAVEPAIR`.

No other stored program deletes `SK2.UUT_RESULT` or `DLCK.UUT_RESULT`. `SK2.RESULTS_UTILITIES` and `DLCK.RESULTS_UTILITIES` delete configuration tables only. No Scheduler job and no legacy job calls `DEL_ALL_OLD_RES_WITH_VERIFY_CLOUD`, and the cursor cache has no recent delete of these two tables, so the last run was issued from outside the database. The warehouse package `SYNC_USER.FLEX_REFRESH` builds a local `DELETE` of `UUT_RESULT` and never executes it.

### Segment size by schema

Synced-table segments only. `Not synced` is the count of other tables in that schema on FLEX.

| Schema | Synced tables | FLEX MB | DWH_CL MB | DWH_CL minus FLEX | Not synced |
|---|---:|---:|---:|---:|---:|
| `SYSTEM_ATE_2` | 12 | 65,350.4 | 62,977.4 | -2,373.0 | 14 |
| `MGLS_SYSTEM` | 12 | 55,884.4 | 55,825.4 | -59.0 | 13 |
| `VF3P_LLI` | 12 | 50,756.4 | 50,635.4 | -121.0 | 18 |
| `IPDE` | 12 | 46,803.4 | 46,638.4 | -165.0 | 12 |
| `MGLSP` | 12 | 45,541.4 | 31,517.4 | -14,024.0 | 13 |
| `FOG` | 12 | 45,389.4 | 45,423.4 | 34.0 | 37 |
| `MGLS` | 12 | 34,559.4 | 24,503.4 | -10,056.0 | 13 |
| `KF3` | 12 | 30,750.7 | 30,709.7 | -41.0 | 12 |
| `IPDE_SYSTEM` | 12 | 27,347.4 | 27,320.4 | -27.0 | 12 |
| `TR5_SYSTEM` | 12 | 27,023.4 | 27,013.4 | -10.0 | 12 |
| `HC` | 12 | 24,876.5 | 24,883.5 | 7.0 | 14 |
| `TR5` | 12 | 19,117.7 | 19,102.7 | -15.0 | 12 |
| `VSF` | 12 | 18,738.3 | 18,741.3 | 3.0 | 12 |
| `EPA` | 12 | 17,637.4 | 16,686.4 | -951.0 | 12 |
| `ISN` | 12 | 13,488.4 | 13,551.4 | 63.0 | 12 |
| `MGLSP_PROG` | 12 | 13,478.4 | 13,475.4 | -3.0 | 12 |
| `GSM_MODULE` | 12 | 10,770.4 | 10,807.4 | 37.0 | 12 |
| `HC_PROG` | 12 | 10,580.3 | 12,156.3 | 1,576.0 | 12 |
| `HC_SYSTEM` | 12 | 9,013.3 | 10,040.3 | 1,027.0 | 13 |
| `ES700OPDI` | 12 | 8,974.4 | 9,006.4 | 32.0 | 12 |
| `IPDEP` | 12 | 8,785.4 | 8,754.4 | -31.0 | 12 |
| `VSF4L_SYSTEM` | 12 | 6,745.8 | 6,786.8 | 41.0 | 13 |
| `ISN_SYSTEM` | 12 | 6,466.4 | 6,441.4 | -25.0 | 12 |
| `HC_KIT` | 12 | 6,446.3 | 6,384.3 | -62.0 | 14 |
| `VSF4L_PROG` | 12 | 6,276.4 | 6,233.4 | -43.0 | 13 |
| `SK2` | 12 | 6,001.4 | 25,646.4 | 19,645.0 | 32 |
| `EPPH` | 12 | 5,980.4 | 5,922.4 | -58.0 | 12 |
| `OPDI_SYSTEM` | 12 | 5,347.4 | 5,355.4 | 8.0 | 12 |
| `IN_PROC_ATE` | 12 | 4,490.5 | 4,462.5 | -28.0 | 12 |
| `IPDEP_SYSTEM` | 12 | 3,970.4 | 3,984.4 | 14.0 | 13 |
| `VPD2` | 12 | 2,001.7 | 2,009.7 | 8.0 | 12 |
| `POWER` | 12 | 1,801.4 | 1,800.4 | -1.0 | 12 |
| `MPERS` | 12 | 1,654.4 | 1,649.4 | -5.0 | 13 |
| `DLCK` | 12 | 1,227.4 | 2,169.4 | 942.0 | 34 |
| `PIR` | 12 | 1,138.4 | 1,146.4 | 8.0 | 13 |
| `FSMB` | 12 | 875.4 | 875.4 | 0.0 | 38 |
| `VPD` | 12 | 564.7 | 564.7 | 0.0 | 13 |
| `RFD` | 12 | 554.5 | 554.5 | 0.0 | 13 |
| `SYSTEM_IOT` | 12 | 503.5 | 502.5 | -1.0 | 13 |
| `S5` | 12 | 415.8 | 415.8 | 0.0 | 12 |
| `SYSTEM_IOT_2` | 12 | 378.4 | 361.4 | -17.0 | 13 |
| `FSCB` | 12 | 260.4 | 261.4 | 1.0 | 34 |
| `SYSTEM_WER` | 12 | 216.2 | 216.2 | 0.0 | 40 |
| `MPERSG1_SYSTEM` | 12 | 201.4 | 201.4 | 0.0 | 13 |
| `JOLI_TREAT_FT` | 12 | 120.1 | 120.1 | 0.0 | 13 |
| `IDPC` | 12 | 104.1 | 104.1 | 0.0 | 12 |
| `SK5` | 12 | 80.4 | 80.4 | 0.0 | 13 |
| `TRKPD` | 12 | 77.2 | 77.2 | 0.0 | 13 |
| `SRN` | 12 | 66.4 | 66.4 | 0.0 | 13 |
| `ES700S5` | 12 | 66.2 | 66.2 | 0.0 | 12 |
| `VF3P` | 12 | 54.4 | 54.4 | 0.0 | 14 |
| `ES901BUL` | 12 | 53.1 | 54.2 | 1.1 | 12 |
| `SMOKE_TUNNEL` | 12 | 52.4 | 52.4 | 0.0 | 12 |
| `JOLI_TREAT_SYSTEM` | 12 | 47.7 | 47.7 | 0.0 | 12 |
| `MGL_WER` | 12 | 45.1 | 45.1 | 0.0 | 14 |
| `MGLM` | 12 | 44.4 | 45.4 | 1.0 | 13 |
| `IPD2_WER` | 12 | 39.9 | 39.9 | 0.0 | 13 |
| `JOLI_ANALYZER_FT` | 12 | 32.0 | 32.0 | 0.0 | 12 |
| `UFC` | 12 | 30.2 | 30.2 | 0.0 | 15 |
| `PIR_WER` | 12 | 28.8 | 28.8 | 0.0 | 13 |
| `MS_SYSTEM` | 12 | 28.1 | 28.1 | 0.0 | 13 |
| `HCPSTN` | 12 | 27.1 | 27.1 | 0.0 | 12 |
| `IPD` | 12 | 25.5 | 25.5 | 0.0 | 12 |
| `SK5_SYSTEM` | 12 | 25.0 | 25.0 | 0.0 | 12 |
| `CANS` | 12 | 21.4 | 21.4 | 0.0 | 13 |
| `JAMMING_DETECTOR` | 12 | 17.1 | 17.1 | 0.0 | 13 |
| `SYSTEM_MPERS_GEN` | 12 | 16.7 | 16.7 | 0.0 | 13 |
| `CANS_SYSTEM` | 12 | 9.0 | 9.1 | 0.1 | 13 |
| `BUL2_SYSTEM` | 12 | 8.1 | 8.1 | 0.0 | 13 |
| `JOLI_CRADLE_FT` | 12 | 7.8 | 7.8 | 0.0 | 13 |
| `VF4` | 12 | 5.0 | 5.0 | 0.0 | 13 |
| `VE_VPD2` | 12 | 4.7 | 4.7 | 0.0 | 12 |
| `ZWAVE` | 12 | 3.8 | 3.8 | 0.0 | 12 |
| `OCTOPLUS` | 12 | 3.2 | 3.2 | 0.0 | 13 |
| `EPF` | 12 | 2.1 | 2.2 | 0.1 | 12 |
| `SOLITION_TECH` | 12 | 1.0 | 0.9 | -0.1 | 13 |
| `JIG_CARDS` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `SECURE_TAG` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `ES700OPDI_TEST` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `RMA_SORTING` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `MPERS_SYS_2` | 12 | 0.7 | 0.7 | 0.0 | 13 |
| `EP` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `HC_TELIT_PROG` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `CM_DB_UPDATE` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `LABELING` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `IPDEP_SYSEM` | 12 | 0.7 | 0.7 | 0.0 | 13 |
| `ACOUSTIC_SYS` | 12 | 0.7 | 0.7 | 0.0 | 13 |
| `MGL` | 12 | 0.7 | 0.7 | 0.0 | 12 |
| `LMS` | 12 | 0.7 | 0.7 | 0.0 | 12 |
