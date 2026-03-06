@echo off
SETLOCAL

SET NEW_BRANCH=%1

IF "%NEW_BRANCH%"=="" (
    ECHO [ERROR] No branch name provided.
    ECHO Usage: make switch b=^<branch-name^>
    EXIT /B 1
)

ECHO ============================================================
ECHO  Switching environment to: %NEW_BRANCH%
ECHO ============================================================
ECHO.

REM --- Step 1: Save current branch images ---
ECHO [1/5] Saving current image tags...
make stash-tags
ECHO.

REM --- Step 2: Backup current DB volume ---
ECHO [2/5] Backing up current volume data...
make backup
ECHO.

REM --- Step 3: Checkout target branch ---
ECHO [3/5] Switching to branch: %NEW_BRANCH%...
git checkout %NEW_BRANCH%
IF %ERRORLEVEL% NEQ 0 (
    ECHO [ERROR] git checkout failed. Aborting — your current state is intact.
    EXIT /B 1
)
ECHO.

REM --- Step 4: Load cached images for new branch ---
ECHO [4/5] Loading cached images for new branch...
make apply-tags
ECHO.

REM --- Step 5: Restore DB volume ---
ECHO [5/5] Restoring volume data for new branch...
make apply-backup
ECHO.

ECHO ============================================================
ECHO  Done! Now run:  make start-prod
ECHO  Docker will rebuild only changed layers (fast if cached).
ECHO ============================================================
ENDLOCAL
