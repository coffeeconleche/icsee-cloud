. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location $cameraRoot
try {
    & $cameraPython -m icsee_cloud stop
    if ($LASTEXITCODE -ne 0) { throw 'The recorder could not be stopped' }
} finally { Pop-Location }
