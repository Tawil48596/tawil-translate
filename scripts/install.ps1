param([string]$InstallDir = "$env:LOCALAPPDATA\TawilTranslate")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$api = "https://api.github.com/repos/Tawil48596/tawil-translate/releases/latest"
Write-Host "Finding latest Tawil Translate release..."
$release = Invoke-RestMethod -Uri $api -Headers @{"User-Agent"="TawilTranslateInstaller"}
$asset = $release.assets | Where-Object name -eq "tawil-translate-windows-x64.zip" | Select-Object -First 1
if (-not $asset) { throw "The latest release has no Windows x64 package." }
$archive = Join-Path $env:TEMP "tawil-translate-windows-x64.zip"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive
if (Test-Path $InstallDir) {
    $backup = "$InstallDir.previous"
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    Move-Item $InstallDir $backup
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Expand-Archive -Path $archive -DestinationPath $InstallDir -Force
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Tawil Translate.lnk")
$shortcut.TargetPath = Join-Path $InstallDir "TawilTranslate.exe"
$shortcut.WorkingDirectory = $InstallDir
$shortcut.Save()
Write-Host "Installed to $InstallDir"
Write-Host "Launch Tawil Translate from the Start menu."
