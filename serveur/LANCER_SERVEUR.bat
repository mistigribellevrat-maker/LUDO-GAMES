@echo off
REM Lance le serveur de scores DICTATION WAR et le redemarre automatiquement
REM s'il s'arrete (crash, coupure reseau, etc).
REM
REM Pour un demarrage automatique avec Windows (sans service) : mettre un
REM raccourci vers ce fichier dans le dossier de demarrage de l'utilisateur
REM (touche Windows + R, taper "shell:startup", coller le raccourci ici).
REM
REM Logs applicatifs dans server.log (a cote de ce fichier). Ctrl+C dans cette
REM fenetre puis "O" (oui) a l'invite pour tout arreter.

setlocal
pushd "%~dp0"

:loop
echo ============================================
echo   DICTATION WAR - Serveur de scores
echo   %date% %time%
echo ============================================
python server.py
echo.
echo Le serveur s'est arrete. Redemarrage dans 5 secondes...
echo (Ctrl+C puis "O" pour tout arreter)
timeout /t 5
goto loop
