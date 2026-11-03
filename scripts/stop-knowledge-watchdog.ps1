$ErrorActionPreference = 'Stop'
$knowledgeRoot = Split-Path -Parent $PSScriptRoot
$watchdogPidFile = Join-Path $knowledgeRoot 'data\manuals\runtime\connection-watchdog\watchdog.pid'
$watchdogPython = Join-Path $env:USERPROFILE '.conda\envs\design-rag\python.exe'
if (Test-Path -LiteralPath $watchdogPidFile) {
    $watchdogRecordedId = [int](Get-Content -LiteralPath $watchdogPidFile -Raw)
    $watchdogExisting = Get-CimInstance Win32_Process -Filter "ProcessId = $watchdogRecordedId"
    if ($watchdogExisting) {
        if ($watchdogExisting.ExecutablePath -ine $watchdogPython -or $watchdogExisting.CommandLine -notlike '*knowledge_connection_watchdog.py*') {
            throw 'Recorded watchdog PID belongs to another process.'
        }
        Stop-Process -Id $watchdogRecordedId
    }
    Remove-Item -LiteralPath $watchdogPidFile
}
Write-Output 'DingTalk connection watchdog stopped; bot and knowledge services unchanged.'
