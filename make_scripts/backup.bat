@echo off
ECHO Backing up volume data...
SETLOCAL

SET VOLUME_NAME=crew_pdgata
SET BACKUP_DIR=.\\make_scripts\\backups

REM Get the current Git branch name
FOR /F "tokens=*" %%a IN ('git rev-parse --abbrev-ref HEAD') DO SET BRANCH_NAME=%%a

IF "%BRANCH_NAME%"=="" (
    ECHO ERROR: Could not determine Git branch. Make sure you are in a Git repository.
    GOTO :EOF
)

ECHO Branch %BRANCH_NAME%
ECHO Volume %VOLUME_NAME%

REM Create backups directory if it doesn't exist
IF NOT EXIST "%BACKUP_DIR%" (
    ECHO Creating %BACKUP_DIR% directory...
    MKDIR "%BACKUP_DIR%"
)

SET BACKUP_FILE=%BACKUP_DIR%\\%BRANCH_NAME%.tar
ECHO Creating archive %BACKUP_FILE%...

REM Run a temporary container to create a tar archive of the volume
REM %cd% works here because 'make' has already CRed to the project root
docker run --rm -v "%VOLUME_NAME%":/volume_data -v "%cd%\\make_scripts\\backups":/backup_dir alpine tar -cf /backup_dir/%BRANCH_NAME%.tar -C /volume_data .

IF %ERRORLEVEL% EQU 0 (
    ECHO Backup complete: %BACKUP_FILE%
) ELSE (
    ECHO ERROR Backup failed.
)

ENDLOCAL