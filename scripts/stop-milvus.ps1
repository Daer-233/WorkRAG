$ErrorActionPreference = 'Stop'
$milvusRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $milvusRoot
docker compose -p workknowledge-milvus -f instances/milvus/compose.yaml stop
if ($LASTEXITCODE -ne 0) { throw 'Milvus stop failed; inspect Docker Desktop and compose status.' }
