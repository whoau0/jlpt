@echo off
chcp 65001 > nul
title 키라키라 (Kirakira) - AI 일본어 실시간 전화 통화
cd /d "%~dp0"

echo =================================================================
echo   🌟 키라키라(キラキラ) 실행을 준비합니다...
echo   잠시 후 웹 브라우저(http://localhost:8000)가 열립니다!
echo =================================================================
echo.

:: 1. 현재 폴더 venv 확인
if exist "venv\Scripts\python.exe" (
    echo [실행] 가상환경(venv)으로 키라키라를 시작합니다...
    venv\Scripts\python.exe web_server.py
    goto done
)

:: 2. 상위 폴더 venv 확인
if exist "..\venv\Scripts\python.exe" (
    echo [실행] 상위 가상환경(..\venv)으로 키라키라를 시작합니다...
    ..\venv\Scripts\python.exe web_server.py
    goto done
)

:: 3. py 런처 확인
where py >nul 2>nul
if %errorlevel% == 0 (
    echo [실행] py 런처로 키라키라를 시작합니다...
    py web_server.py
    goto done
)

:: 4. 시스템 전역 python 확인
where python >nul 2>nul
if %errorlevel% == 0 (
    echo [실행] 시스템 Python으로 키라키라를 시작합니다...
    python web_server.py
    goto done
)

echo [⚠️ 오류] Python 실행 환경을 찾을 수 없습니다!
echo.
echo 원인:
echo 1) 현재 폴더에 'venv' 가상환경이 생성되어 있지 않습니다.
echo 2) 또는 PC에 파이썬이 설치되어 있지 않거나 환경변수(PATH)에 등록되지 않았습니다.
echo.
echo -----------------------------------------------------------------
echo [해결 안내]
echo 1. Python이 미설치된 경우:
echo    https://www.python.org/downloads/ 에서 Python 3.11 이상 설치
echo    (※ 설치 창 맨 아래 'Add python.exe to PATH' 반드시 체크!)
echo.
echo 2. 설치 후 가상환경 생성 명령어:
echo    python -m venv venv
echo    venv\Scripts\pip install -r requirements.txt
echo -----------------------------------------------------------------
echo.

:done
echo.
pause
