$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\deployment\local.py" start
if ($LASTEXITCODE -ne 0) { throw 'WorkRAG startup failed; inspect data\manuals\runtime\local.' }
