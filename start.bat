@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动议程后端：http://127.0.0.1:8080
echo 首次配对地址里带令牌，看下面输出。
python server.py --port 8080
pause
