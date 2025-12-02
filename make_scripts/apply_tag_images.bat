@echo off
ECHO Applying stashed branch tags to images...
SETLOCAL

REM Get the current Git branch name
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a

IF "%BRANCH_NAME%"=="" (
    ECHO ERROR Could not determine Git branch. Make sure you are in a Git repository.
    GOTO :EOF
)

ECHO Applying tags from branch %BRANCH_NAME%
ECHO.

REM Loop through each image and re-tag it from the branch tag
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
    ECHO Tagging %%i:%BRANCH_NAME% as %%i...
    docker tag %%i:%BRANCH_NAME% %%i
)

ECHO.
ECHO All images re-tagged.
ENDLOCAL