param([int]$Port = 8766)
. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location $cameraRoot
try { & $cameraPython -m icsee_cloud watch --port $Port; exit $LASTEXITCODE }
finally { Pop-Location }
