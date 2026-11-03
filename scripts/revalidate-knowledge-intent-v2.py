"""Revalidate additional abstention guards; never fit against an opened test."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/manuals/runtime/intent-v2-guard-base'
OUT=ROOT/'data/manuals/intent/v2'
DELIVERY=ROOT/'output/intent-routing-v2'


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    cal=load_module('v2_revalidation_calibrator',ROOT/'scripts/calibrate-knowledge-intent-v2.py')
    original=json.loads((BASE/'calibration.json').read_text(encoding='utf-8'))
    baseline=json.loads((BASE/'acceptance.json').read_text(encoding='utf-8'))
    assert cal.digest(BASE/'factors.py')==original['fingerprint']['factors.py']
    old=(BASE/'factors.py').read_text(encoding='utf-8');new=(ROOT/'apps/backend/app/manuals/intent/factors.py').read_text(encoding='utf-8')
    anchor='        return list(dict.fromkeys(reasons))\n'
    extra="        if output=='text' and not s.provided_text:\n            wants_visual=s.visual or (contains(s.instruction,policy()['visual_markers']) and contains(s.instruction,['我要','我需要']))\n            if wants_visual or s.file:reasons.append('explicit_media_request_cannot_be_silently_text')\n"
    assert old.count(anchor)==1 and new==old.replace(anchor,extra+anchor),'Changes must be additional abstentions only'
    stamp=cal.fingerprint(cal.MODEL)
    changed={key for key in stamp if stamp[key]!=original['fingerprint'].get(key)}
    assert changed<={'factors.py','calibrate-knowledge-intent-v2.py'},'Unexpected classifier/data changes'
    old_script=(BASE/'calibrator.py').read_text(encoding='utf-8');new_script=(ROOT/'scripts/calibrate-knowledge-intent-v2.py').read_text(encoding='utf-8')
    old_line="dataset_role='fresh_independent_v2_acceptance'"
    new_line="dataset_role=artifact.get('evaluation_role','fresh_independent_v2_acceptance')"
    assert new_script==old_script.replace(old_line,new_line),'Calibration logic must remain unchanged'
    sets,audit=cal.audit();legacy=cal.load_rows('regression-v1',version='v2')
    old_module=load_module('app.manuals.intent._frozen_v2_factors',BASE/'factors.py')
    old_model=old_module.FactorBM25(sets['index']);new_model=cal.FactorBM25(sets['index'])
    monotone={}
    for name,rows in [('calibration',sets['calibration']),('acceptance',sets['acceptance']),('regression',legacy)]:
        before=cal.evaluate_rows(rows,old_model,original);after=cal.evaluate_rows(rows,new_model,original)
        assert all(b['prediction'] is None or b['prediction']==a['prediction'] for a,b in zip(before['cases'],after['cases']))
        monotone[name]={'cases':len(rows),'new_direct_routes':0,'removed_direct_routes':sum(a['prediction'] is not None and b['prediction'] is None for a,b in zip(before['cases'],after['cases']))}
    selected=deepcopy(original);selected.update(fingerprint=stamp,evaluation_role='fixed_v2_holdout_replay_after_monotone_guards_no_refit',
        original_calibration_sha256=cal.digest(BASE/'calibration.json'),threshold_values_sha256=canonical(original['bm25_axes']),
        monotone_revalidation=monotone)
    assert canonical(selected['bm25_axes'])==canonical(original['bm25_axes'])
    for folder in (OUT,DELIVERY):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'acceptance-initial-independent.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'calibration.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
    cal.evaluate(sets,audit)
    (DELIVERY/'monotone-guard-proof.json').write_text(json.dumps({'thresholds_unchanged':True,'proof':'Exact source comparison: only append a blocker; calibration change is report role only','groups':monotone},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'thresholds_unchanged':True,'monotone':monotone},ensure_ascii=False))


if __name__=='__main__':main()
