$ErrorActionPreference = 'Stop'
$milvusRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $milvusRoot
docker compose -p workknowledge-milvus -f instances/milvus/compose.yaml up -d
if ($LASTEXITCODE -ne 0) { throw 'Milvus startup failed; inspect Docker Desktop and compose status.' }
docker compose -p workknowledge-milvus -f instances/milvus/compose.yaml ps
