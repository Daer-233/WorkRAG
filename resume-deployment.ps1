$ErrorActionPreference = 'Stop'
$workragDocker = 'G:\docker\Desktop\resources\bin\docker.exe'
$workragPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $workragDocker info --format '{{.ServerVersion}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    Start-Process -FilePath 'G:\docker\Desktop\Docker Desktop.exe' -WindowStyle Hidden
    $workragEngineReady = $false
    for ($workragAttempt=0; $workragAttempt -lt 90; $workragAttempt++) {
        Start-Sleep -Seconds 2
        & $workragDocker info --format '{{.ServerVersion}}' 2>$null
        if ($LASTEXITCODE -eq 0) { $workragEngineReady = $true; break }
    }
    if (-not $workragEngineReady) { throw 'Docker engine unavailable. Complete the required Windows restart and inspect Docker Desktop.' }
}
& $workragPython "$PSScriptRoot\deployment\local.py" start
if ($LASTEXITCODE -ne 0) { throw 'Service startup failed.' }
& $workragPython "$PSScriptRoot\deployment\checks\verify_local.py"
if ($LASTEXITCODE -ne 0) { throw 'Deployment acceptance failed.' }
& $workragPython "$PSScriptRoot\deployment\local.py" stop
if ($LASTEXITCODE -ne 0) { throw 'Service restart check failed while stopping.' }
& $workragPython "$PSScriptRoot\deployment\local.py" start
if ($LASTEXITCODE -ne 0) { throw 'Service restart check failed while starting.' }
& $workragPython "$PSScriptRoot\deployment\checks\verify_local.py"
if ($LASTEXITCODE -ne 0) { throw 'Persistence verification failed.' }
Write-Output 'Verified WorkRAG: http://127.0.0.1:8060/knowledge/ ; LangBot: http://127.0.0.1:5300'
