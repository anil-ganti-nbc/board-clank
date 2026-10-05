@echo off
setlocal
set "REPO=C:\Users\anil\Clanks\board-clank"
if not exist "%REPO%\pyproject.toml" (
  echo ERROR: Board Clank repository not found at "%REPO%"
  exit /b 1
)
cd /d "%REPO%"
if not exist "%REPO%\.venv\Scripts\board-clank.exe" (
  echo ERROR: Board Clank CLI not found in .venv
  exit /b 1
)
"%REPO%\.venv\Scripts\board-clank.exe" --db "%REPO%\data\board.sqlite" ui --research-db "%REPO%\data\research.sqlite"
exit /b %ERRORLEVEL%
