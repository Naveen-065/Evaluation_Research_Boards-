# Run manually to activate the tested API update. Never stops a hardware job.
$ErrorActionPreference = 'Stop'
$benchRoot = $PSScriptRoot
$benchUri = 'http://127.0.0.1:8771/api/status'
$expectedRevision = 'ssh-startup-retry-v1'
$benchState = Invoke-RestMethod $benchUri
if ($benchState.api_revision -eq $expectedRevision) {
    Write-Host 'The updated API is already running; no restart needed.'
    exit 0
}
if ($benchState.busy) { throw 'A hardware job is running; restart refused.' }
$listeners = @(Get-NetTCPConnection -LocalPort 8771 -State Listen)
if ($listeners.Count -ne 1) { throw 'Expected exactly one local GUI listener.' }
$serverPid = $listeners[0].OwningProcess
$serverInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
if ($serverInfo.Name -ne 'python.exe' -or
    $serverInfo.CommandLine -notmatch 'gui[/\\]server\.py --port 8771') {
    throw 'The listener is not the expected SenseEval Python server; nothing stopped.'
}
$manifestPath = Join-Path $benchRoot 'evidence\deployment.json'
$manifestBefore = [System.IO.File]::ReadAllText($manifestPath)
$utf8 = New-Object System.Text.UTF8Encoding $false
$maintenance = $manifestBefore | ConvertFrom-Json
$maintenance.ready = $false
$maintenance.reason = 'GUI/API maintenance: activating SSH connection recovery.'
[System.IO.File]::WriteAllText($manifestPath, ($maintenance | ConvertTo-Json -Depth 30), $utf8)
if ((Invoke-RestMethod $benchUri).busy) {
    [System.IO.File]::WriteAllText($manifestPath, $manifestBefore, $utf8)
    throw 'A hardware job started before maintenance; nothing stopped.'
}
Write-Host "Restarting only the local GUI server (PID $serverPid, port 8771)."
Stop-Process -Id $serverPid -ErrorAction Stop
Wait-Process -Id $serverPid -Timeout 10 -ErrorAction SilentlyContinue
$newGui = Start-Process -FilePath $serverInfo.ExecutablePath `
    -ArgumentList '-u','gui/server.py','--port','8771' `
    -WorkingDirectory $benchRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $benchRoot 'evidence\gui_transport_fix_stdout.log') `
    -RedirectStandardError (Join-Path $benchRoot 'evidence\gui_transport_fix_stderr.log') `
    -PassThru
$runningStatus = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try { $runningStatus = Invoke-RestMethod $benchUri; break } catch { }
}
if ($runningStatus.api_revision -ne $expectedRevision) {
    throw 'Updated API not confirmed. The maintenance gate remains closed; inspect the GUI server stderr log.'
}
[System.IO.File]::WriteAllText($manifestPath, $manifestBefore, $utf8)
Write-Host "Updated API verified: $expectedRevision (PID $($newGui.Id))."
Write-Host 'Reload http://127.0.0.1:8771/ and use Check bench. This script sends no FPGA commands.'
