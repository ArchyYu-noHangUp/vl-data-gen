$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/ArchyYu-noHangUp/vl-data-gen.git" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "windows-server" }
$AppRoot = if ($env:APP_ROOT) { $env:APP_ROOT } else { "C:\vl-data-gen" }

function Install-LocalFfmpeg {
    param([string]$Root)

    $ffmpegBin = Join-Path $Root "tools\ffmpeg\bin"
    $ffmpegExe = Join-Path $ffmpegBin "ffmpeg.exe"
    $ffprobeExe = Join-Path $ffmpegBin "ffprobe.exe"
    if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
        return
    }

    Write-Host "未检测到系统 ffmpeg，正在下载 Windows 版 ffmpeg 到项目目录..."
    $downloadDir = Join-Path $Root "tools"
    $zipPath = Join-Path $downloadDir "ffmpeg-release-essentials.zip"
    $extractDir = Join-Path $downloadDir "ffmpeg-download"
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
    $inner = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    if (!$inner) {
        throw "ffmpeg 压缩包解压失败。"
    }
    New-Item -ItemType Directory -Force -Path $ffmpegBin | Out-Null
    Copy-Item -Force -Path (Join-Path $inner.FullName "bin\ffmpeg.exe") -Destination $ffmpegExe
    Copy-Item -Force -Path (Join-Path $inner.FullName "bin\ffprobe.exe") -Destination $ffprobeExe
    Remove-Item -Recurse -Force $extractDir, $zipPath -ErrorAction SilentlyContinue
}

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "未检测到 git。请先安装 Git for Windows。"
}

if (!(Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "未检测到 Python Launcher。请先安装 Python 3.11，并勾选 Add python.exe to PATH。"
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
New-Item -ItemType Directory -Force -Path data, runs, logs, sample_dataset, temp_final, tools | Out-Null

if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue) -or !(Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Install-LocalFfmpeg -Root $AppRoot
}

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "安装完成。启动命令："
Write-Host "cd $AppRoot"
Write-Host "powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1"
