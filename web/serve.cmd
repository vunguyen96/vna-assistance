@echo off
rem vna-assistance-web · guaranteed auto-load launcher.
rem Serves the data folder locally so index.html reads the live CSV in any
rem browser (Chrome included), then opens it. No install; needs Python.

setlocal
rem Data folder: honour VNA_HOME, else default to %USERPROFILE%\vna-assistance.
if defined VNA_HOME (set "DATA=%VNA_HOME%") else (set "DATA=%USERPROFILE%\vna-assistance")
set "WEB=%~dp0"
set "PORT=8777"

if not exist "%DATA%\vna-assistance.csv" (
  echo No CSV found at %DATA%\vna-assistance.csv
  echo Add a note first with: python vna-assistance-cli.py note "..."
  pause
  exit /b 1
)

rem Refresh the app files inside the data folder so they are never stale.
copy /Y "%WEB%index.html" "%DATA%\index.html" >nul
copy /Y "%WEB%app.js"     "%DATA%\app.js"     >nul
copy /Y "%WEB%styles.css" "%DATA%\styles.css" >nul

cd /d "%DATA%"
start "" "http://localhost:%PORT%/index.html"
echo Serving %DATA% at http://localhost:%PORT%/  (Ctrl+C to stop)
python -m http.server %PORT%
