"""Display names may change; resolve integrations by their persistent UUIDs."""
import json
from pathlib import Path

AGENT_NAME='调试助手'
PIPELINE_NAME='问答流水线'
MCP_NAME='资料检索工具'
LEGACY_MCP_NAME='WorkRAGReadOnly'

def resolve_mcp_server(servers):
    binding=Path(__file__).resolve().parents[1]/'data/manuals/runtime/agent-deployment/binding.json'
    server_id=json.loads(binding.read_text(encoding='utf-8')).get('mcp_server_id') if binding.exists() else None
    return next((s for s in servers if s['uuid']==server_id),None) or next(
        (s for s in servers if s['name'] in (MCP_NAME,LEGACY_MCP_NAME)),None)
