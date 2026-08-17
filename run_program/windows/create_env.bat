@echo off
setlocal

set ENV_FILE=%~dp0..\.env
set SIGNING_FILE=%~dp0..\.signing.env
set CURRENT_PATH=%cd%
set TARGET_PATH=%CURRENT_PATH:\=/%
set TARGET_PATH=%TARGET_PATH%/savefiles/

>"%ENV_FILE%" echo CREW_SAVEFILES_PATH="%TARGET_PATH%"

break > "%SIGNING_FILE%.new"
if exist "%SIGNING_FILE%" findstr /b /r "^SECRET_KEY=. ^JWT_SECRET=." "%SIGNING_FILE%" >> "%SIGNING_FILE%.new"

:: Generate whichever key is still missing.
call :ensure_key SECRET_KEY
call :ensure_key JWT_SECRET

move /y "%SIGNING_FILE%.new" "%SIGNING_FILE%" >nul
echo Environment written to %ENV_FILE%
echo Signing keys kept in %SIGNING_FILE% (generated once, reused afterwards)
goto :eof

:ensure_key
findstr /b "%1=" "%SIGNING_FILE%.new" >nul 2>&1 && goto :eof
for /f "delims=" %%K in ('powershell -NoProfile -Command "$b=New-Object byte[] 48;[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b);[Convert]::ToBase64String($b) -replace '[=+/]',''"') do >>"%SIGNING_FILE%.new" echo %1=%%K
goto :eof
