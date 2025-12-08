@echo off
setlocal

set PYTHON_310="C:\Program Files\Python310\python.exe"
set PYTHON_311="C:\Program Files\Python311\python.exe"
set PYTHON_312="C:\Program Files\Python312\python.exe"
set PYTHON_313="C:\Program Files\Python313\python.exe"
set PYTHON_314="C:\Program Files\Python314\python.exe"

%PYTHON_314% -m mypy asyncpg_typed
if errorlevel 1 goto error
%PYTHON_314% -m mypy test
if errorlevel 1 goto error

if exist %PYTHON_310% %PYTHON_310% -m unittest discover
if errorlevel 1 goto error
if exist %PYTHON_311% %PYTHON_311% -m unittest discover
if errorlevel 1 goto error
if exist %PYTHON_312% %PYTHON_312% -m unittest discover
if errorlevel 1 goto error
if exist %PYTHON_313% %PYTHON_313% -m unittest discover
if errorlevel 1 goto error
if exist %PYTHON_314% %PYTHON_314% -m unittest discover
if errorlevel 1 goto error

%PYTHON_314% -m ruff check
if errorlevel 1 goto error
%PYTHON_314% -m ruff format
if errorlevel 1 goto error

goto EOF

:error
exit /b %errorlevel%

:EOF
