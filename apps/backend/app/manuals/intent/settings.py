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
    value={'mode':'off','version':'intent-v2-factors','sample_set':'v2','model_path':str(MODEL),'terra_enabled':True}
    if CONFIG.exists(): value.update(read_json(CONFIG))
    if value['mode'] not in ('off','shadow','on'): raise ValueError('Invalid intent mode')
    path=Path(value['model_path']).resolve()
    if not path.is_relative_to((DATA/'models/intent').resolve()): raise ValueError('Intent model directory is outside its model root')
    value['model_path']=str(path)
    if value['sample_set'] not in ('v1','v2','v3'):raise ValueError('Unknown intent sample set')
    return value


def sample_path(version=None):
    version=version or config().get('sample_set','v2')
    if version not in ('v1','v2','v3'):raise ValueError('Unknown intent sample set')
    return SAMPLES if version=='v1' else SAMPLES/version


def report_dir(cfg):return DATA/'intent' if cfg.get('sample_set','v2')=='v1' else DATA/'intent'/cfg.get('sample_set','v2')


def fingerprint(model_path,version=None):
    version=version or config()['sample_set']
    manifest=Path(model_path)/'intent-manifest.json'
    files=[sample_path(version)/name for name in ('index.jsonl','calibration.jsonl','acceptance.jsonl')]
    files.append(ROOT/'instances/manuals/intent-policy.v2.json')
    code=[Path(__file__).parent/name for name in ('bm25.py','factors.py','nli.py','engine.py','types.py','terra.py','settings.py')]
    host=ROOT/'scripts/knowledge_card/intent_host.py'
    calibrator=ROOT/'scripts'/('calibrate-knowledge-intent-v3.py' if version=='v3' else 'calibrate-knowledge-intent-v2.py')
    if version=='v3':
        files += [sample_path(version)/name for name in ('train.jsonl','development.jsonl')]
        code += [Path(__file__).parent/'supervised.py',ROOT/'scripts/train-knowledge-intent-v3.py',ROOT/'scripts/prepare-intent-v3.py']
    return {str(p.name):digest(p) for p in files+code+[host,calibrator]}|{'model_manifest':digest(manifest) if manifest.exists() else None,'sample_set':version}


def load_rows(name,version=None):
    return [json.loads(line) for line in (sample_path(version)/(name+'.jsonl')).read_text(encoding='utf-8').splitlines() if line.strip()]


def calibration_valid(cfg):
    try:
        artifact=read_json(report_dir(cfg)/'calibration.json')
        return artifact if artifact.get('fingerprint')==fingerprint(cfg['model_path'],cfg.get('sample_set','v2')) else None
    except (OSError,ValueError): return None


def activation_valid(cfg):
    try:
        report=read_json(report_dir(cfg)/'acceptance.json')
        return bool(report.get('passed') and report.get('integration_passed') and
                    report.get('shadow_passed') and report.get('human_review')=='complete' and report.get('fingerprint')==fingerprint(cfg['model_path'],cfg.get('sample_set','v2')))
    except (OSError,ValueError): return False
