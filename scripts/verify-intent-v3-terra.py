"""Probe Terra fallback with a synthetic long question; no platform message."""
import json
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
question='请用通俗语言解释天气预报中的气压和降雨有什么关系。'*12
with httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},timeout=30,trust_env=False) as client:
    reply=client.post('/api/v1/manuals/intent/route',json={'text':question}).raise_for_status().json()
report={key:reply[key] for key in ('intent','method','mode','reason','elapsed_ms','local_elapsed_ms')}
report.update(synthetic=True,employee_messages_sent=0,terra_reached=reply['method']=='terra',
              safe_fallback=reply['method']=='fallback' and reply['intent']=='clarify')
(ROOT/'output/intent-routing-v3/terra-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
