@echo off
rem luciazero-agentd -- run the Agent Bus daemon from anywhere, on Windows.
rem lucia -- the same program under a shorter name, installed as a second copy.
rem
rem luciazero-managed: agentd-launcher
rem
rem The Windows counterpart of bin/luciazero-agentd, step for step; that file
rem says why each step is there. What is Windows' own:
rem
rem   * This file is LF, as every file in the repository is, and cmd.exe can
rem     misread labels in an LF batch file, so there is no label and no goto.
rem   * Every value that may hold a path is set and compared in quotes, and no
rem     path is ever expanded inside a parenthesised block: a directory such as
rem     "C:\Program Files (x86)" ends a block that names it bare.
rem   * cmd.exe looks for a command in the working directory before PATH, so
rem     Python is found through PATH alone and run by its full path; a
rem     python.exe beside the caller is never the one that runs.
rem   * cmd.exe reads a file in the console's code page, which mangles a UTF-8
rem     path outside ASCII, so the recorded package path is read by Python.
rem   * Arguments pass through as cmd.exe parsed them. Quote an argument that
rem     holds & | < > or ^, as at any cmd.exe prompt.
setlocal EnableExtensions DisableDelayedExpansion

set "LZ_PACKAGE="
set "LZ_HOME_FILE="
if defined LUCIAZERO_AGENTD_HOME set "LZ_PACKAGE=%LUCIAZERO_AGENTD_HOME%"
rem Checkout layout wins over the recorded one: running bin\luciazero-agentd.cmd
rem out of a second clone must use that clone, not whichever one was installed.
rem Only when %~f0 is this file: run by a quoted name found on PATH ("lucia"),
rem cmd.exe reports the working directory as this file's, and the caller's
rem ..\agentd would be taken for the checkout.
if not defined LZ_PACKAGE if exist "%~f0" if exist "%~dp0..\agentd\luciazero_agentd\" for %%I in ("%~dp0..\agentd") do set "LZ_PACKAGE=%%~fI"
set "LZ_CONFIG=%USERPROFILE%\.claude"
if defined CLAUDE_CONFIG_DIR set "LZ_CONFIG=%CLAUDE_CONFIG_DIR%"
if not defined LZ_PACKAGE if exist "%LZ_CONFIG%\.luciazero-agentd-home" set "LZ_HOME_FILE=%LZ_CONFIG%\.luciazero-agentd-home"

if not defined LZ_PACKAGE if not defined LZ_HOME_FILE >&2 echo %~n0: cannot find the luciazero_agentd package. It ships in a checkout of https://github.com/ohm41321/luciazero, not in the npm package. Clone it and run the installer from the checkout, or point LUCIAZERO_AGENTD_HOME at its agentd directory.
if not defined LZ_PACKAGE if not defined LZ_HOME_FILE exit /b 127

rem ADR 0002: try python3, then python, then the Windows launcher, and take the
rem first one that reports 3.10 or newer. The Microsoft Store's python.exe
rem stand-in fails this check, as it should.
set "LZ_PY="
for %%P in (python3.exe python.exe) do if not defined LZ_PY if not "%%~$PATH:P"=="" "%%~$PATH:P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "LZ_PY="%%~$PATH:P""
for %%P in (py.exe) do if not defined LZ_PY if not "%%~$PATH:P"=="" "%%~$PATH:P" -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "LZ_PY="%%~$PATH:P" -3"
if not defined LZ_PY >&2 echo %~n0: needs Python 3.10 or newer; tried python3, python and py -3
if not defined LZ_PY exit /b 127

rem The package travels in an environment variable and the working directory
rem is taken off sys.path, exactly as in bin/luciazero-agentd; both variables
rem are popped before the daemon starts. This file's own variables are cleared
rem on the line that starts Python, after that line has read them, so neither
rem the daemon nor a provider it starts inherits them.
set "LUCIAZERO_AGENTD_PACKAGE=%LZ_PACKAGE%"
set "LUCIAZERO_AGENTD_HOME_FILE=%LZ_HOME_FILE%"
set "LUCIAZERO_ARGV0=%~n0"
set "LZ_PACKAGE=" & set "LZ_HOME_FILE=" & set "LZ_CONFIG=" & set "LZ_PY=" & %LZ_PY% -c "import os, sys, runpy; package = os.environ.pop('LUCIAZERO_AGENTD_PACKAGE', ''); recorded = os.environ.pop('LUCIAZERO_AGENTD_HOME_FILE', ''); package = package or open(recorded, encoding='utf-8').readline().rstrip('\r\n'); os.path.isdir(os.path.join(package, 'luciazero_agentd')) or (print(os.environ['LUCIAZERO_ARGV0'] + ': no luciazero_agentd package in ' + package + ' (moved or deleted checkout?). Re-run the installer from the checkout, or set LUCIAZERO_AGENTD_HOME.', file=sys.stderr), sys.exit(127)); sys.path = [entry for entry in sys.path if entry not in ('', '.', os.getcwd())]; sys.path.insert(0, package); runpy.run_module('luciazero_agentd', run_name='__main__', alter_sys=True)" %*
exit /b %ERRORLEVEL%
