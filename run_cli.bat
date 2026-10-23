@echo off
chcp 65001 > nul
title 키라키라 (Kirakira) - 터미널 모드
cd /d "%~dp0"
venv\Scripts\python.exe main.py
pause
