param([ValidateSet('low','high')][string]$Quality='high', [switch]$VideoOnly, [ValidateRange(0,24)][double]$Hours=0,
      [ValidatePattern('^[1-9][0-9]{0,4}x[1-9][0-9]{0,4}$')][string]$MinimumResolution)
. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location $cameraRoot
try {
    # Validate before stopping a working recording.
    if ($MinimumResolution) {
        & $cameraPython -c 'import sys; from icsee_cloud.media import parse_resolution; parse_resolution(sys.argv[1])' $MinimumResolution
        if ($LASTEXITCODE -ne 0) { throw 'Invalid minimum resolution' }
    }
    & $cameraPython -m icsee_cloud stop
    if ($LASTEXITCODE -ne 0) { throw 'Previous recorder could not be stopped' }
    $recordStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $recordFolder = Join-Path $cameraRoot ('recordings\jobs\' + $recordStamp)
    $recordJob = Join-Path $recordFolder 'job.json'
    $recordTaskName = 'iCSee-Cloud-' + $recordStamp
    $recordArguments = @('-m','icsee_cloud','record','--create','--prepare','--job',$recordJob,'--quality',$Quality)
    if ($Hours -gt 0) { $recordArguments += @('--hours', "$Hours") }
    else { $recordArguments += '--indefinite' }
    if (-not $VideoOnly) { $recordArguments += '--audio' }
    if ($MinimumResolution) { $recordArguments += @('--minimum-resolution', $MinimumResolution) }
    & $cameraPython @recordArguments
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the recording job' }
    $cameraPythonWindowless = Join-Path (Split-Path $cameraPython -Parent) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $cameraPythonWindowless)) { throw 'A Windows Python installation with pythonw.exe is required' }
    # This entry point lives in the installed package and receives a private job path.
    $recordAction = New-ScheduledTaskAction -Execute $cameraPythonWindowless -Argument ('-m icsee_cloud record --job "' + $recordJob + '"') -WorkingDirectory $cameraRoot
    $recordUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $recordPrincipal = New-ScheduledTaskPrincipal -UserId $recordUser -LogonType Interactive -RunLevel Limited
    $recordTimer = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $recordLogon = New-ScheduledTaskTrigger -AtLogOn -User $recordUser
    $recordSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $recordTaskName -Action $recordAction -Trigger @($recordTimer,$recordLogon) -Principal $recordPrincipal -Settings $recordSettings -Description 'Authenticated iCSee recording until the configured deadline or manual Stop.' | Out-Null
    Set-Content -LiteralPath (Join-Path $recordFolder 'scheduled-task.txt') -Value $recordTaskName
    Start-ScheduledTask -TaskName $recordTaskName
    Write-Output ('Recording task started: ' + $recordTaskName)
    Write-Output ('Job metadata: ' + $recordFolder)
    Write-Output 'Viewer: http://127.0.0.1:8766/'
    Write-Output 'Stop manually: ./scripts/Stop-Recording.ps1'
} finally { Pop-Location }
