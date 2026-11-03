import hashlib
import json
from pathlib import Path

from ..isolation import DATA, ROOT

CONFIG=DATA/'intent/config.json'
SAMPLES=ROOT/'instances/manuals/intent-samples'
MODEL=DATA/'models/intent/erlangshen-110m-nli'


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def config():
    value={'mode':'shadow','version':'intent-v1','model_path':str(MODEL),'terra_enabled':True}
    if CONFIG.exists(): value.update(read_json(CONFIG))
    if value['mode'] not in ('off','shadow','on'): raise ValueError('Invalid intent mode')
    path=Path(value['model_path']).resolve()
    if not path.is_relative_to((DATA/'models/intent').resolve()): raise ValueError('Intent model directory is outside its model root')
    value['model_path']=str(path)
    return value


def fingerprint(model_path):
    manifest=Path(model_path)/'intent-manifest.json'
    files=[SAMPLES/'index.jsonl',SAMPLES/'calibration.jsonl',SAMPLES/'acceptance.jsonl']
    code=[Path(__file__).parent/name for name in ('bm25.py','nli.py','engine.py','types.py','terra.py')]
    host=ROOT/'scripts/knowledge_card/intent_host.py'
    return {str(p.name):digest(p) for p in files+code+[host]}|{'model_manifest':digest(manifest) if manifest.exists() else None}


def load_rows(name):
    return [json.loads(line) for line in (SAMPLES/(name+'.jsonl')).read_text(encoding='utf-8').splitlines() if line.strip()]


def calibration_valid(cfg):
    try:
        artifact=read_json(DATA/'intent/calibration.json')
        return artifact if artifact.get('fingerprint')==fingerprint(cfg['model_path']) else None
    except (OSError,ValueError): return None


def activation_valid(cfg):
    try:
        report=read_json(DATA/'intent/acceptance.json')
        return bool(report.get('passed') and report.get('integration_passed') and
                    report.get('shadow_passed') and report.get('fingerprint')==fingerprint(cfg['model_path']))
    except (OSError,ValueError): return False
