@echo off
REM ---------------------------------------------------------------------------
REM e-con DepthVista Helix iToF - Isaac Sim uninstaller (Windows)
REM
REM Reverts EVERYTHING build.bat did, returning Isaac Sim to stock:
REM   - restores the Full app .kit files from their .bak (removes the dependency lines),
REM   - removes both extensions from <isaac>\extsUser.
REM Same Isaac-Sim detection as build.bat: env -> common locations -> ask.
REM
REM Usage:  uninstall.bat   (or)   set ISAACSIM_PATH=C:\path\to\isaacsim ^& uninstall.bat
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
if not defined EXT_NAMES set "EXT_NAMES=econ.itof.menu econ.itof.ros"

REM ── Locate Isaac Sim (same logic as build.bat) ───────────────────────────────
if not defined ISAACSIM_PATH if defined ISAAC_SIM_PATH set "ISAACSIM_PATH=%ISAAC_SIM_PATH%"
if not defined ISAACSIM_PATH (
    for %%D in (
        "%LOCALAPPDATA%\ov\pkg\isaac-sim-*"
        "%LOCALAPPDATA%\ov\pkg\isaac_sim-*"
        "%USERPROFILE%\isaacsim"
        "%USERPROFILE%\isaac-sim"
        "%USERPROFILE%\Downloads\isaacsim"
        "%USERPROFILE%\Downloads\isaac-sim*"
        "C:\isaacsim"
        "C:\isaac-sim"
    ) do (
        for /d %%P in (%%~D) do (
            if exist "%%~P\isaac-sim.bat" set "ISAACSIM_PATH=%%~P"
        )
        if not defined ISAACSIM_PATH if exist "%%~D\isaac-sim.bat" set "ISAACSIM_PATH=%%~D"
    )
)

:ask_isaac
if defined ISAACSIM_PATH if exist "%ISAACSIM_PATH%\isaac-sim.bat" goto :have_isaac
echo [WARN] Isaac Sim not auto-detected.
set "ISAACSIM_PATH="
set /p "ISAACSIM_PATH=Enter the Isaac Sim folder (contains isaac-sim.bat), or blank to abort: "
if not defined ISAACSIM_PATH echo [ERROR] Aborted. & exit /b 1
if not exist "%ISAACSIM_PATH%\isaac-sim.bat" echo [ERROR] No isaac-sim.bat in "%ISAACSIM_PATH%". & goto :ask_isaac

:have_isaac
echo [INFO] Using Isaac Sim at: %ISAACSIM_PATH%

REM Revert each extension
set "PYEXE="
where py  >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>&1 && set "PYEXE=python" )
for %%N in (%EXT_NAMES%) do (
    if defined PYEXE (
        "!PYEXE!" "%SCRIPT_DIR%\scripts\patch_kit.py" "%ISAACSIM_PATH%\apps" "%%N" --uninstall || echo [WARN] Could not restore .kit files for %%N.
    ) else (
        echo [ERROR] python not found - cannot restore .kit files automatically.
    )
    if exist "%ISAACSIM_PATH%\extsUser\%%N" rmdir /s /q "%ISAACSIM_PATH%\extsUser\%%N"
    echo [INFO] Removed %ISAACSIM_PATH%\extsUser\%%N
)

echo.
echo [SUCCESS] e-con DepthVista Helix removed. Isaac Sim is back to stock.
echo   Re-install anytime with build.bat
exit /b 0
