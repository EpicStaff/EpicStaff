@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current branch name and sanitize slashes (feature/foo -> feature-foo)
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a
SET BRANCH_SAFE=%BRANCH_NAME:/=-%

IF "%BRANCH_SAFE%"=="" (
    ECHO [ERROR] Could not determine Git branch. Are you inside a git repository?
    EXIT /B 1
)

ECHO [stash-tags] Saving images for branch: %BRANCH_SAFE%
ECHO.

SET SUCCESS=0
SET SKIPPED=0

FOR %%i IN (
    django_app
    crew
    manager
    realtime
    webhook
    sandbox
    knowledge
    frontend
    crewdb
    redis-monitor
) DO (
    docker image inspect %%i >nul 2>&1
    IF !ERRORLEVEL! EQU 0 (
        docker tag %%i %%i:%BRANCH_SAFE% >nul
        ECHO   [SAVED]  %%i  ->  %%i:%BRANCH_SAFE%
        SET /A SUCCESS+=1
    ) ELSE (
        ECHO   [SKIP]   %%i  ^(not built yet^)
        SET /A SKIPPED+=1
    )
)

ECHO.
ECHO Saved: %SUCCESS%   Skipped: %SKIPPED%
ENDLOCAL
