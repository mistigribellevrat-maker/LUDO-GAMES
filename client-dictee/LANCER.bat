@echo off
setlocal
pushd "%~dp0"

REM --- Detection de Python (python, sinon py -3) ---
set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"

echo ==============================================
echo   DICTATION WAR - Lancement du jeu
echo ==============================================
echo.

REM --- 1. Environnement virtuel : cree seulement s'il n'existe pas ---
if not exist "venv\Scripts\python.exe" (
    echo [1/3] Creation de l'environnement virtuel...
    %PY% -m venv venv
    if errorlevel 1 (
        echo.
        echo ERREUR : impossible de creer l'environnement virtuel.
        echo Verifiez que Python 3.12 est installe et accessible.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Environnement virtuel deja present.
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo.
    echo ERREUR : impossible d'activer l'environnement virtuel.
    pause
    exit /b 1
)

REM --- 2. Dependances : installees/mises a jour (rapide si deja a jour) ---
echo [2/3] Verification des dependances...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERREUR : l'installation des dependances a echoue.
    pause
    exit /b 1
)

REM --- 3. Fichier .env : cree depuis le modele si absent ---
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo.
        echo ATTENTION : fichier .env cree depuis .env.example, mais il est vide.
        echo Ouvrez .env et renseignez au moins GEMINI_API_KEY avant de jouer.
        echo Le jeu se lancera mais affichera une erreur tant que la cle n'est pas renseignee.
        echo.
        pause
    ) else (
        echo.
        echo ATTENTION : aucun fichier .env ni .env.example trouve.
        echo Le jeu ne pourra pas generer de dictees sans GEMINI_API_KEY.
        echo.
    )
)

REM --- 4. Lancement du jeu ---
echo [3/3] Lancement du jeu...
echo.
python main.py

echo.
echo Le jeu s'est ferme.
popd
pause
