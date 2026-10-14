$ErrorActionPreference = 'Stop'
$cameraRoot = Split-Path $PSScriptRoot -Parent
$cameraPython = Join-Path $cameraRoot '.venv\Scripts\python.exe'
if ($env:ICSEE_PYTHON) { $cameraPython = $env:ICSEE_PYTHON }
elseif (-not (Test-Path -LiteralPath $cameraPython)) {
    $cameraPython = (Get-Command python.exe -ErrorAction Stop).Source
}
$env:ICSEE_HOME = $cameraRoot
$env:PYTHONPATH = Join-Path $cameraRoot 'src'
