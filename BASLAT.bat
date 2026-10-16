@echo off
title DIY Otonom Kesif Masasi
cd /d "%~dp0"
echo ===================================================
echo   DIY Otonom Kesif ve Proje Masasi Baslatiliyor...
echo ===================================================
echo Tarayici otomatik acilacaktir: http://localhost:8501
streamlit run app.py --server.port 8501
pause
