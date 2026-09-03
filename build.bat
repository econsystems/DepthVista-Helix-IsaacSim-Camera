@echo off
REM ---------------------------------------------------------------------------
REM e-con DepthVista Helix iToF - Isaac Sim installer (Windows)
REM
REM Registers both extensions - econ.itof.menu (camera asset / Create menu) and
REM econ.itof.ros (ROS 2 publish + web viewer + GT viewer) - so they auto-load on
REM every launch. Pure Python - nothing to compile.
REM
REM Usage:
REM   build.bat                            - register the extensions with Isaac Sim
REM   set ISAACSIM_PATH=... ^& build.bat   - skip Isaac Sim auto-detection
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Configuration (override via env)
if not defined EXT_NAMES set "EXT_NAMES=econ.itof.menu econ.itof.ros"
if not defined INSTALL_DIR set "INSTALL_DIR=%SCRIPT_DIR%"

REM 1. Sanity-check each extension is present (do NOT build anything)
for %%N in (%EXT_NAMES%) do (
    if not exist "%INSTALL_DIR%\exts\%%N" (
        echo [ERROR] Extension not found at %INSTALL_DIR%\exts\%%N.
        echo [ERROR] This package must contain exts\%%N\ ^(config\extension.toml + python^).
        exit /b 1
    )
    echo [INFO] Found extension: %INSTALL_DIR%\exts\%%N
)

REM 2. Locate the Isaac Sim install (holds isaac-sim.bat)
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
if not defined ISAACSIM_PATH echo [ERROR] Aborted - no Isaac Sim path given. & exit /b 1
if not exist "%ISAACSIM_PATH%\isaac-sim.bat" echo [ERROR] No isaac-sim.bat in "%ISAACSIM_PATH%". & goto :ask_isaac

:have_isaac
echo [INFO] Using Isaac Sim at: %ISAACSIM_PATH%

set "EXTSUSER=%ISAACSIM_PATH%\extsUser"
if not exist "%EXTSUSER%" mkdir "%EXTSUSER%"

set "PYEXE="
where py  >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>&1 && set "PYEXE=python" )
if not defined PYEXE echo [ERROR] python not found - needed to register the extensions. & exit /b 1

REM 3. Register each extension so it auto-loads: copy into <isaac>\extsUser (on the
REM    search path) and add it to the Full app's .kit [dependencies].
for %%N in (%EXT_NAMES%) do (
    echo [INFO] Copying %%N into %EXTSUSER%\%%N ...
    robocopy "%INSTALL_DIR%\exts\%%N" "%EXTSUSER%\%%N" /MIR /NJH /NJS /NDL /NFL >nul
    "!PYEXE!" "%INSTALL_DIR%\scripts\patch_kit.py" "%ISAACSIM_PATH%\apps" "%%N" || ( echo [ERROR] Could not patch the Isaac Sim .kit files for %%N. & exit /b 1 )
    echo [INFO] Registered %%N.
)

REM 4. Done
echo.
echo [SUCCESS] e-con DepthVista Helix installed ^(auto-loads on every launch^).
echo.
echo   If Isaac Sim is open, fully close and reopen it. Launch normally - no special command.
echo   Then: Create -^> Sensors -^> Camera and Depth Sensors -^> e-con -^> DepthVista Helix iToF
echo   The 'e-con iToF' control window docks next to the Property panel.
echo.
echo   Uninstall (reverts everything): uninstall.bat
exit /b 0
