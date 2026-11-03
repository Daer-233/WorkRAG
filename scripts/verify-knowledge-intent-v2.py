"""Local classification-only probes. Never invoke a platform send or answer run."""
import json
from pathlib import Path
import statistics
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/intent-routing-v2'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[{'entry_id':'00000000-0000-4000-8000-000000000031','title':'合成文件甲','available':True,'kind':'extracted_markdown'}]
    probes=[
        ('company_mixed',{'text':'你好，补卡怎么申请'},'knowledge'),
        ('general_software',{'text':'Excel 怎么筛选'},'daily'),
        ('provided_company_notice',{'text':'润色报销通知：请同事周三交报销单'},'daily'),
        ('missing_notice_text',{'text':'润色报销通知'},'clarify'),
        ('requested_file',{'text':'发我报销模板'},'source_file'),
        ('existing_images',{'text':'请找知识库里的志愿活动照片'},'images'),
        ('known_file_offer',{'text':'需要','previous_sources':sources,'previous_file_offer':True},'source_file'),
        ('multiple_file_offer',{'text':'发给我','previous_sources':sources+[dict(sources[0],entry_id='00000000-0000-4000-8000-000000000032',title='合成文件乙')],'previous_file_offer':True},'clarify'),
        ('only_uploaded_image',{'attachment_types':['image']},'clarify'),
        ('company_with_uploaded_image',{'text':'公司系统登录显示AUTH12，应找谁处理','attachment_types':['image']},'knowledge'),
        ('negated_output',{'text':'别给图片，我要公司制度的文字说明'},'knowledge'),
        ('reference_without_context',{'text':'这个和那个有什么区别'},'clarify'),
    ]
    records=[]
    with httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},timeout=26,trust_env=False) as client:
        status=client.get('/api/v1/manuals/intent/status');status.raise_for_status();status=status.json()
        assert status['effective_mode']=='shadow' and status['version']=='intent-v2-factors' and status['calibrated']
        for name,payload,expected in probes:
            started=time.perf_counter();response=client.post('/api/v1/manuals/intent/route',json=payload);response.raise_for_status();value=response.json()
            records.append({'case':name,'expected':expected,'intent':value['intent'],'axes':value['axes'],'layer':value['method'],
                'mode':value['mode'],'has_image':value['has_image'],'reason':value['reason'],
                'local_elapsed_ms':value['local_elapsed_ms'],'elapsed_ms':value['elapsed_ms'],
                'http_elapsed_ms':round((time.perf_counter()-started)*1000,2),'passed':value['intent']==expected})
            print(name,value['intent'],value['method'],records[-1]['passed'],flush=True)
            (OUT/'live-classification-probes.json').write_text(json.dumps({'records':records,'employee_messages_sent':0},ensure_ascii=False,indent=2),encoding='utf-8')
        # The fast-path benchmark is explicitly limited to calibrated BM25
        # cases; it is not end-to-end latency or a claim about Terra speed.
        from importlib.util import module_from_spec,spec_from_file_location
        spec=spec_from_file_location('v2cal',ROOT/'scripts/calibrate-knowledge-intent-v2.py');module=module_from_spec(spec);spec.loader.exec_module(module)
        sets,_=module.audit();artifact=json.loads((ROOT/'data/manuals/intent/v2/calibration.json').read_text(encoding='utf-8'))
        model=module.FactorBM25(sets['index'])
        eligible=[r for r in sets['calibration'] if module.preflight(module.request(r)) is None and model.decide(module.request(r),artifact['bm25_axes'])[0] is not None][:3]
        latencies=[];http_latencies=[]
        for i in range(30):
            payload=module.request(eligible[i%len(eligible)]).model_dump(mode='json')
            start=time.perf_counter();r=client.post('/api/v1/manuals/intent/route',json=payload);r.raise_for_status();value=r.json()
            assert value['method']=='bm25_axes' and value['mode']=='shadow'
            latencies.append(value['local_elapsed_ms']);http_latencies.append((time.perf_counter()-start)*1000)
        latency={'scope':'warm local API BM25 fast path only, three calibration questions repeated 30 times; excludes Terra and answer generation',
            'samples':len(latencies),'local_p95_ms':module.p95(latencies),'http_p95_ms':round(module.p95(http_latencies),2),'employee_messages_sent':0}
        (OUT/'local-api-latency.json').write_text(json.dumps(latency,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'passed':all(r['passed'] for r in records),'cases':len(records),'employee_messages_sent':0,'latency':latency}
    (OUT/'probe-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
