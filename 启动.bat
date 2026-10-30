@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [Competition Radar] 正在清理旧进程...
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in 8000,8501} | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

echo [Competition Radar] 启动后端 (127.0.0.1:8000) ...
start "Competition Radar 后端" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"

timeout /t 3 /nobreak >nul

echo [Competition Radar] 启动前端 (localhost:8501) ...
start "Competition Radar 前端" cmd /k ".venv\Scripts\python.exe -m streamlit run ui.py --server.headless true"

timeout /t 5 /nobreak >nul

echo [Competition Radar] 打开浏览器 ...
start http://localhost:8501

echo.
echo 已启动完成。
echo   前端网页: http://localhost:8501
echo   后端接口: http://127.0.0.1:8000/docs
echo 关闭：直接关闭两个弹出的命令行窗口即可。
echo.
pause
