@echo off
chcp 65001 >nul
title DeepSeek Chat - 打包程序包

echo ============================================
echo  DeepSeek Chat - 桌面版打包脚本
echo ============================================
echo.

:: 确保在项目目录下运行
cd /d "%~dp0"

:: ====================================================================
:: 0. 清理旧的构建文件
:: ====================================================================
echo [0/5] 清理旧的构建文件...
if exist "dist" rmdir /s /q "dist" 2>nul
if exist "build" rmdir /s /q "build" 2>nul
if exist "DeepSeekChat.spec" del "DeepSeekChat.spec" 2>nul
echo ✅ 清理完成
echo.

:: ====================================================================
:: 1. 安装依赖
:: ====================================================================
echo [1/5] 安装 Python 依赖...
if exist ".venv\Scripts\pip.exe" (
    .venv\Scripts\pip.exe install -r requirements-desktop.txt
) else (
    pip install -r requirements-desktop.txt
)
if %errorlevel% neq 0 (
    echo ❌ 依赖安装失败，请检查网络或手动安装
    pause
    exit /b 1
)
echo ✅ 依赖安装完成
echo.

:: ====================================================================
:: 2. 生成鲸鱼图标（从 icon.png 生成圆形多尺寸 ICO）
:: ====================================================================
echo [2/5] 生成鲸鱼图标（圆形裁剪）...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe convert_icon.py
) else (
    python convert_icon.py
)
if %errorlevel% neq 0 (
    echo ⚠️ convert_icon.py 失败，尝试旧的 generate_icon.py...
    if exist ".venv\Scripts\python.exe" (
        .venv\Scripts\python.exe generate_icon.py
    ) else (
        python generate_icon.py
    )
    if %errorlevel% neq 0 (
        if not exist "whale.ico" (
            echo 跳过图标，PyInstaller 将使用默认图标
        )
    )
)
echo.

:: ====================================================================
:: 3. 安装 PyInstaller
:: ====================================================================
echo [3/5] 安装 PyInstaller...
if exist ".venv\Scripts\pip.exe" (
    .venv\Scripts\pip.exe install pyinstaller
) else (
    pip install pyinstaller
)
echo.

:: ====================================================================
:: 4. 打包（使用 --onedir 模式，生成文件夹）
:: ====================================================================
echo [4/5] 正在打包（文件夹模式），请等待...

if exist ".venv\Scripts\pyinstaller.exe" (
    set PYI=.venv\Scripts\pyinstaller.exe
) else (
    set PYI=pyinstaller
)

%PYI% --onedir --windowed ^
    --icon=whale.ico ^
    --name "DeepSeekChat" ^
    --add-data "templates;templates" ^
    --hidden-import flask ^
    --hidden-import openai ^
    --hidden-import yaml ^
    --hidden-import webview ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    --collect-all webview ^
    --collect-all flask ^
    desktop_app.py

if %errorlevel% neq 0 (
    echo ❌ 打包失败
    pause
    exit /b 1
)
echo ✅ PyInstaller 打包完成
echo.

:: ====================================================================
:: 5. 组装发布包
:: ====================================================================
echo [5/5] 组装最终发布包...

:: 5a. 创建目标目录
set OUTPUT_DIR=dist\deepseek_chat
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%" 2>nul
mkdir "%OUTPUT_DIR%" 2>nul

:: 5b. 移动到 deepseek_chat 目录
move "dist\DeepSeekChat\DeepSeekChat.exe" "%OUTPUT_DIR%\" >nul
move "dist\DeepSeekChat\_internal" "%OUTPUT_DIR%\" >nul

:: 5c. 复制数据文件到顶层（exe 同目录）
copy "config.yaml" "%OUTPUT_DIR%\" >nul
if exist "whale.ico" copy "whale.ico" "%OUTPUT_DIR%\" >nul

:: 5d. 创建数据目录
if not exist "%OUTPUT_DIR%\history" mkdir "%OUTPUT_DIR%\history"

:: 5e. 清理中间产物
if exist "dist\DeepSeekChat" rmdir /s /q "dist\DeepSeekChat" 2>nul
if exist "build" rmdir /s /q "build" 2>nul

echo.
echo ================================================================
echo ✅ 打包完成！
echo.
echo 📦 发布包位置:
echo     dist\deepseek_chat\
echo.
echo 目录结构:
echo     dist\deepseek_chat\
echo     ├── DeepSeekChat.exe     （主程序，双击运行）
echo     ├── _internal\           （运行时组件，请勿删除）
echo     ├── config.yaml          （配置文件，可编辑）
echo     ├── history\             （对话历史记录）
echo     └── memories.json        （记忆数据，运行后自动生成）
echo.
echo 📋 使用说明:
echo   - 双击 deepseek_chat\DeepSeekChat.exe 即可运行
echo   - 编辑 config.yaml 修改 API 密钥等配置
echo   - 设置界面可在程序右上角齿轮按钮打开
echo   - 将整个 deepseek_chat 文件夹发给朋友即可使用
echo ================================================================
pause
