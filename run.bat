@echo off
setlocal
set "PYTHON_EXE=python"
where python >nul 2>nul
if errorlevel 1 (
  set "PYTHON_EXE=py"
)
"%PYTHON_EXE%" app.py
