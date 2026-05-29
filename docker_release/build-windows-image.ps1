$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$ImageName = if ($env:IMAGE_NAME) { $env:IMAGE_NAME } else { "vl-data-gen:0.4.2-windows" }
$Output = if ($env:OUTPUT) { $env:OUTPUT } else { "docker_release\vl-data-gen-0.4.2-windows.tar" }

docker build --file Dockerfile.windows --tag $ImageName .
docker save --output $Output $ImageName

Write-Host "Windows Docker image saved to: $Output"
