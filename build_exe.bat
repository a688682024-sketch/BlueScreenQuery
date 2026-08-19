@echo off
chcp 65001 >nul
title 蓝屏代码查询器 - 一键打包

echo ========================================
echo    蓝屏代码查询器 - 一键打包工具
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

echo [1/4] 检查依赖...
pip install -r requirements.txt -q
echo [完成]

echo [2/4] 检查PyInstaller...
pip install pyinstaller -q
echo [完成]

echo [3/4] 清理旧文件...
if exist "dist\BlueScreenQuery" rmdir /s /q "dist\BlueScreenQuery"
if exist "build" rmdir /s /q "build"
if exist "BlueScreenQuery.spec" del "BlueScreenQuery.spec"
echo [完成]

echo [4/4] 正在打包，请耐心等待...
echo.

pyinstaller --onefile --windowed --name "BlueScreenQuery" ^
    --add-data "bluescreen_data.json;." ^
    --icon NONE ^
    --clean ^
    --noconfirm ^
    blue_screen_query.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo    打包成功！
    echo    输出路径：dist\BlueScreenQuery.exe
    echo ========================================
) else (
    echo.
    echo [错误] 打包失败，请检查错误信息
)

pause