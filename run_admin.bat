@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0run.bat' -WorkingDirectory '%~dp0' -Verb RunAs"
