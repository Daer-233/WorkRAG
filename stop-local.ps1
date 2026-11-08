$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\deployment\local.py" stop
if ($LASTEXITCODE -ne 0) { throw 'WorkRAG stop failed.' }
