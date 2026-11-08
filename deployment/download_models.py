"""Fetch CPU inference artifacts from ModelScope and record their hashes."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

os.environ.setdefault('MODELSCOPE_CACHE','G:/docker/cache/modelscope')
from modelscope import snapshot_download

kind = sys.argv[1]
model_id = 'BAAI/bge-m3' if kind=='embedding' else 'BAAI/bge-reranker-v2-m3'
target = Path('G:/docker/models') / model_id.split('/')[1]
weights = 'pytorch_model.bin' if kind=='embedding' else 'model.safetensors'
snapshot_download(model_id=model_id, revision='master', local_dir=str(target), max_workers=3,
                  allow_patterns=['*.json','*.txt','*.model',weights,'sparse_linear.pt','colbert_linear.pt'])
if not (target/weights).is_file(): raise RuntimeError('Model weights missing')
artifacts={}
for path in target.rglob('*'):
    if path.is_file() and path.suffix in {'.bin','.safetensors','.pt','.json','.model','.txt'} and not path.name.endswith('manifest.json'):
        h=hashlib.sha256()
        with path.open('rb') as file:
            for chunk in iter(lambda:file.read(8*1024*1024),b''): h.update(chunk)
        artifacts[str(path.relative_to(target))]={'bytes':path.stat().st_size,'sha256':h.hexdigest()}
manifest={'provider':'modelscope','model_id':model_id,'source_revision':'master','local_dir':str(target),
          'artifact_files':artifacts,'downloaded_at_utc':datetime.now(timezone.utc).isoformat()}
manifest['pytorch_weights_sha256' if kind=='embedding' else 'model_weights_sha256']=artifacts[weights]['sha256']
(target/'design-rag-model-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(kind,'downloaded and hashed',flush=True)
