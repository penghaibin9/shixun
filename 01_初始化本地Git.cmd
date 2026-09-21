@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo 跃科网络空间安全实训平台 - 初始化本地 Git
echo ==========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [失败] 当前电脑没有找到 Git。
    echo 请先安装 Git for Windows，然后重新双击本文件。
    echo.
    pause
    exit /b 1
)

if exist ".git" (
    echo [提示] 当前目录已经是 Git 仓库，不重复初始化。
) else (
    git init -b main
    if errorlevel 1 (
        echo [失败] Git 初始化失败。
        pause
        exit /b 1
    )
    echo [完成] 已创建本地 Git 仓库，当前分支 main。
)

echo.
echo 下一步：
echo 1. 用 Codex 打开本文件夹。
echo 2. 先运行“窗口0”任务。
echo 3. 让 Codex 完成首次提交和 P0-CONTRACT-FREEZE。
echo.
echo 注意：本脚本不会上传 GitHub，也不会联网推送代码。
echo.
pause
