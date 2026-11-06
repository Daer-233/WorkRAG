param(
    [switch]$Reload,
    [Alias('Host')]
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8030
)
$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path -Parent $PSScriptRoot
$backendPython = $null
$pythonCandidates = @(
    (Join-Path $backendRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE '.conda\envs\design-rag\python.exe')
)
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        try {
            & $candidate --version *> $null
            $candidateWorks = $LASTEXITCODE -eq 0
        } catch { $candidateWorks = $false }
        if ($candidateWorks) { $backendPython = $candidate; break }
    }
}
$backendArgs = @((Join-Path $PSScriptRoot 'backend-instance.py'), '--host', $ListenHost, '--port', "$Port")
if ($Reload) { $backendArgs += '--reload' }
Push-Location -LiteralPath $backendRoot
try {
    if ($backendPython) { & $backendPython @backendArgs }
    elseif (Get-Command conda -ErrorAction SilentlyContinue) { conda run -n design-rag python @backendArgs }
    else { throw 'No working project or design-rag Python environment found.' }
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
} finally { Pop-Location }
