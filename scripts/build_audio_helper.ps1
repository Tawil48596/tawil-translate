param(
    [string]$Source = "$PSScriptRoot\..\native\audio_capture",
    [string]$Output = "$PSScriptRoot\..\bin"
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake was not found. Install Visual Studio Build Tools with Desktop development with C++."
}
if (-not (Test-Path "$Source\CMakeLists.txt")) {
    throw "Native helper source is not present yet. See native/audio_capture/README.md."
}
cmake -S $Source -B "$Source\build" -A x64
cmake --build "$Source\build" --config Release
New-Item -ItemType Directory -Force -Path $Output | Out-Null
Copy-Item "$Source\build\Release\tawil-audio-capture.exe" $Output -Force
