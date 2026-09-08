@echo off
findstr /m "Error" test_log.log 
if %errorlevel%==0 (
echo Error was Found! and logged >> test_log.log
SmtpMailSender.exe test Subject ; test Body; tzachar@essence-grp.com ; test_log.log
) else (
echo No Errors found
)