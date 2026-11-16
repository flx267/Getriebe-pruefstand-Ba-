@echo off
REM Baut die Getriebepruefstand-Software als .exe (Ergebnis: dist\Getriebepruefstand\)
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name Getriebepruefstand ^
    --add-data "ui/assets;ui/assets" ^
    --hidden-import Automation.BDaq ^
    main.py
pause
