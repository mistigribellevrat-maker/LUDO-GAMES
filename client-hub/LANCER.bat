@echo off
setlocal
pushd "%~dp0"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"

echo ==============================================
echo   BASE DE COMMANDEMENT - Choix de la mission
echo ==============================================
echo.

REM --- 1. Environnement virtuel : cree seulement s'il n'existe pas ---
if not exist "venv\Scripts\python.exe" (
    echo [1/2] Creation de l'environnement virtuel...
    %PY% -m venv venv
    if errorlevel 1 (
        echo.
        echo ERREUR : impossible de creer l'environnement virtuel.
        echo Verifiez que Python 3.12 est installe et accessible.
        pause
        exit /b 1
    )
) else (
    echo [1/2] Environnement virtuel deja present.
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo.
    echo ERREUR : impossible d'activer l'environnement virtuel.
    pause
    exit /b 1
)

REM --- 2. Dependances : installees/mises a jour (rapide si deja a jour) ---
echo [2/2] Verification des dependances...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERREUR : l'installation des dependances a echoue.
    pause
    exit /b 1
)

echo.
python main.py

echo.
echo Le hub s'est ferme.
popd
pause
