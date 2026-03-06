@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

REM Get current branch name and sanitize slashes
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a
SET BRANCH_SAFE=%BRANCH_NAME:/=-%

IF "%BRANCH_SAFE%"=="" (
    ECHO [ERROR] Could not determine Git branch. Are you inside a git repository?
    EXIT /B 1
)

ECHO [apply-tags] Loading cached images for branch: %BRANCH_SAFE%
ECHO.

SET RESTORED=0
SET MISSING=0

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
    docker image inspect %%i:%BRANCH_SAFE% >nul 2>&1
    IF !ERRORLEVEL! EQU 0 (
        docker tag %%i:%BRANCH_SAFE% %%i >nul
        ECHO   [LOADED] %%i:%BRANCH_SAFE%  ->  %%i
        SET /A RESTORED+=1
    ) ELSE (
        ECHO   [MISS]   No cache for %%i:%BRANCH_SAFE%
        SET /A MISSING+=1
    )
)

ECHO.
IF %RESTORED% GTR 0 (
    ECHO Cache loaded: %RESTORED% image^(s^). Next build will reuse layers and be fast.
) ELSE (
    ECHO No cached images found for branch '%BRANCH_SAFE%'. First build will take longer.
)
IF %MISSING% GTR 0 (
    ECHO Missing: %MISSING% image^(s^) — those will be built from scratch.
)
ENDLOCAL
