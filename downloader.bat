@echo off
setlocal

:: Define variables
set "ZIP_URL=https://github.com/EpicStaff/EpicStaff/archive/refs/heads/main.zip"
set "TMP_ZIP=epicstaff.zip"
set "EXTRACTED_DIR=EpicStaff-main"
set "SRC_DIR=%EXTRACTED_DIR%\run_program"
set "TARGET_DIR=run_program"

echo Downloading ZIP archive...
curl -L -o "%TMP_ZIP%" "%ZIP_URL%"
if errorlevel 1 (
    echo ❌ Failed to download ZIP.
    exit /b 1
)

echo Extracting run_program folder...
powershell -Command "Expand-Archive -Path '%TMP_ZIP%' -DestinationPath '.' -Force"

if not exist "%SRC_DIR%" (
    echo ❌ run_program folder not found in archive.
    del "%TMP_ZIP%"
    exit /b 1
)

:: Create target directory if it doesn't exist
if not exist "%TARGET_DIR%" (
    mkdir "%TARGET_DIR%"
)

:: Merge contents (overwrite existing files)
xcopy "%SRC_DIR%\*" "%TARGET_DIR%\" /E /Y /I

:: Clean up
rd /s /q "%EXTRACTED_DIR%"
del "%TMP_ZIP%"

echo ✅ run_program folder merged successfully into %TARGET_DIR%
endlocal
