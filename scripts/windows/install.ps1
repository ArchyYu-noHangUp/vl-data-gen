$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/ArchyYu-noHangUp/vl-data-gen.git" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "windows-server" }
$AppRoot = if ($env:APP_ROOT) { $env:APP_ROOT } else { "C:\vl-data-gen" }

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "未检测到 git。请先安装 Git for Windows。"
}

if (!(Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "未检测到 Python Launcher。请先安装 Python 3.11，并勾选 Add python.exe to PATH。"
}

if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "未检测到 ffmpeg。请先安装 ffmpeg，并将 ffmpeg.exe 加入 PATH。"
}

if (!(Test-Path $AppRoot)) {
    git clone --branch $Branch $RepoUrl $AppRoot
} else {
    Set-Location $AppRoot
    git fetch origin $Branch
    git checkout $Branch
    git pull --ff-only origin $Branch
}

Set-Location $AppRoot
New-Item -ItemType Directory -Force -Path data, runs, logs, sample_dataset, temp_final | Out-Null

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "安装完成。启动命令："
Write-Host "cd $AppRoot"
Write-Host "powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1"
