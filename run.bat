@echo off
title AI Shorts Video API - LOGS
:: Color verde sobre negro para máxima legibilidad de logs
color 0A

echo ====================================================
echo    SISTEMA DE RENDERIZADO AI SHORTS - STATUS
echo ====================================================
echo.

:: 1. Activar el entorno virtual de forma segura
echo [INFO] Cargando entorno virtual (.venv)...
if not exist ".\.venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] No se encuentra el entorno virtual en .\.venv
    pause
    exit
)
call .\.venv\Scripts\activate

:: 2. Ejecutar Python con logs en tiempo real
:: -u fuerza a Python a mostrar los prints al momento (unbuffered)
echo [INFO] Lanzando API en http://localhost:8000
echo [INFO] Presiona Ctrl+C para detener el servidor.
echo ----------------------------------------------------
echo.

".\.venv\Scripts\python.exe" -u main.py

echo.
echo ----------------------------------------------------
echo [ALERTA] El servidor se ha detenido de forma inesperada.
echo [LOG] Revisa los mensajes de arriba para detectar el error.
pause
