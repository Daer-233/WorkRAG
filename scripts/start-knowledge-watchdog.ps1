$ErrorActionPreference = 'Stop'
$knowledgeRoot = Split-Path -Parent $PSScriptRoot
$watchdogRoot = Join-Path $knowledgeRoot 'data\manuals\runtime\connection-watchdog'
$watchdogPython = Join-Path $env:USERPROFILE '.conda\envs\design-rag\python.exe'
$watchdogScript = Join-Path $PSScriptRoot 'knowledge_connection_watchdog.py'
if (-not (Test-Path -LiteralPath $watchdogPython)) { throw 'The design-rag Python environment is missing.' }
New-Item -ItemType Directory -Force -Path $watchdogRoot | Out-Null
$watchdogPidFile = Join-Path $watchdogRoot 'watchdog.pid'
if (Test-Path -LiteralPath $watchdogPidFile) {
    $watchdogRecordedId = [int](Get-Content -LiteralPath $watchdogPidFile -Raw)
    $watchdogExisting = Get-CimInstance Win32_Process -Filter "ProcessId = $watchdogRecordedId"
    if ($watchdogExisting) {
        if ($watchdogExisting.ExecutablePath -ine $watchdogPython -or $watchdogExisting.CommandLine -notlike '*knowledge_connection_watchdog.py*') {
            throw 'Recorded watchdog PID belongs to another process.'
        }
        Write-Output 'DingTalk connection watchdog already running.'
        return
    }
}
$watchdogProcess = Start-Process -FilePath $watchdogPython -ArgumentList @('-u', $watchdogScript, '--serve', '--recover') -WorkingDirectory $knowledgeRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $watchdogRoot 'watchdog.out.log') -RedirectStandardError (Join-Path $watchdogRoot 'watchdog.err.log')
$watchdogProcess.Id | Set-Content -LiteralPath $watchdogPidFile
Write-Output 'DingTalk connection watchdog started; status is saved locally.'
