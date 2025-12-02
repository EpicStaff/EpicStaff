@echo off
ECHO Importing volume data...
SETLOCAL

SET VOLUME_NAME=crew_pdgata
SET BACKUP_DIR=.\\make_scripts\\backups

REM Get the current Git branch name
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a

IF "%BRANCH_NAME%"=="" (
    ECHO ERROR Could not determine Git branch. Make sure you are in a Git repository.
    GOTO :EOF
)

ECHO Branch: %BRANCH_NAME%
ECHO Volume: %VOLUME_NAME%
SET BACKUP_FILE=%BACKUP_DIR%\\%BRANCH_NAME%.tar

REM Check if backup file exists
IF NOT EXIST "%BACKUP_FILE%" (
    ECHO ERROR Backup file not found %BACKUP_FILE%
    GOTO :EOF
)

REM 1. Run docker compose down
REM Assuming 'src' is at the project root, as 'make' runs this from the root
ECHO Stopping services (docker compose --project-directory .\\src down)...
docker compose --project-directory .\\src down
IF %ERRORLEVEL% NEQ 0 (
    ECHO Warning 'docker compose down' command failed or had issues.
)

REM 2. Import data
ECHO Restoring data from %BACKUP_FILE%...
ECHO WARNING: This will DELETE all current data in volume %VOLUME_NAME% and replace it.

REM %cd% works here because 'make' has already CRed to the project root
docker run --rm -v "%VOLUME_NAME%":/volume_data -v "%cd%\\make_scripts\\backups":/backup_dir alpine sh -c "rm -rf /volume_data/* && tar -xf /backup_dir/%BRANCH_NAME%.tar -C /volume_data"

IF %ERRORLEVEL% EQU 0 (
    ECHO Restore complete.
) ELSE (
    ECHO ERROR Restore failed.
)

ENDLOCAL