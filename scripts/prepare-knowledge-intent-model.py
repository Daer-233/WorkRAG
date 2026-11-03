"""Explicit model preparation; runtime never downloads model files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
MODEL_ID='Fengshenbang/Erlangshen-RoBERTa-110M-NLI'
REVISION='v1.0.0'


def main():
    p=argparse.ArgumentParser();p.add_argument('--download',action='store_true');args=p.parse_args()
    target=ROOT/'data/manuals/models/intent/erlangshen-110m-nli'
    manifest=target/'intent-manifest.json'
    if manifest.exists():
        saved=json.loads(manifest.read_text(encoding='utf-8'))
        for name,value in saved['files'].items():
            f=(target/name).resolve()
            if not f.is_relative_to(target.resolve()) or hashlib.file_digest(f.open('rb'),'sha256').hexdigest()!=value:
                raise RuntimeError('Pinned model verification failed')
        print(json.dumps({'status':'verified','revision':saved['revision'],'files':len(saved['files'])}));return
    if not args.download:raise SystemExit('Use --download for explicit preparation.')
    from modelscope import snapshot_download
    cached=Path(snapshot_download(MODEL_ID,revision=REVISION))
    names=['config.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','tokenizer.json']
    weight=next((n for n in ('model.safetensors','pytorch_model.bin') if (cached/n).exists()),None)
    if not weight:raise RuntimeError('Expected sequence-classification weights missing')
    names.append(weight);target.mkdir(parents=True,exist_ok=True)
    files={}
    for name in names:
        source=cached/name
        if source.exists():
            shutil.copy2(source,target/name)
            with (target/name).open('rb') as stream:files[name]=hashlib.file_digest(stream,'sha256').hexdigest()
    config=json.loads((target/'config.json').read_text(encoding='utf-8'))
    labels=config.get('id2label',{})
    if len([v for v in labels.values() if str(v).casefold() in ('entail','entailment','蕴含')])!=1:
        raise RuntimeError('Entailment label missing or ambiguous; model is not enabled')
    manifest.write_text(json.dumps({'model_id':MODEL_ID,'revision':REVISION,'files':files,
        'id2label':labels,'trust_remote_code':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'prepared','revision':REVISION,'files':len(files)}))


if __name__=='__main__':main()
