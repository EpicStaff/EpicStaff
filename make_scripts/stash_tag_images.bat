@echo off
ECHO Stashing images with branch tag...
SETLOCAL

REM Get the current Git branch name
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a

IF "%BRANCH_NAME%"=="" (
    ECHO ERROR Could not determine Git branch. Make sure you are in a Git repository.
    GOTO :EOF
)

ECHO Tagging for branch: %BRANCH_NAME%
ECHO.

REM Loop through each image and tag it
FOR %%i IN (
    webhook
    django_app
    realtime
    manager
    crewdb
    redis
    redis-monitor
    crew
) DO (
    ECHO Tagging %%i as %%i:%BRANCH_NAME%...
    docker tag %%i %%i:%BRANCH_NAME%
)

ECHO.
ECHO All images tagged.
ENDLOCAL