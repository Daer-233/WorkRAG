"""Create reviewed synthetic procedures with real image assets; never company policy."""
import hashlib
import json
import sys
import time
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from docx import Document
from docx.shared import Inches
import httpx
from install_agent import ROOT,RUNTIME,client,data

DEST=ROOT/'data/manuals/runtime/demo-enterprise'
CASES=[('设备借用演练','WRAG-DEMO-EQUIP-01',[
    ('登记需求','填写设备名称、用途和预计归还日期，演练用途统一填写“联调测试”。'),
    ('核对编号','确认设备编号为 DEMO-LAPTOP-008；点击蓝色“确认借用”按钮。'),
    ('归还登记','归还后记录“外观正常”，点击“提交归还”，演练完成。')]),
    ('服务工单演练','WRAG-DEMO-TICKET-02',[
    ('创建工单','演练系统选择“测试环境”，工单标题填写“打印机联调测试”。'),
    ('选择分类','故障分类选择“设备连接”，工单编号为 DEMO-TICKET-016；点击橙色“提交工单”按钮。'),
    ('关闭工单','确认演练处理结果为“连接已恢复”，点击“确认关闭”。')])]

def prepare():
    DEST.mkdir(parents=True,exist_ok=True)
    backend=httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},trust_env=False,timeout=240)
    def call(method,path,**kw):r=backend.request(method,path,**kw);r.raise_for_status();return r.json()
    report={'synthetic':True,'not_company_policy':True,'documents':[]}
    font=lambda n:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',n)
    existing=call('GET','/api/v1/manuals/entries')
    for title,marker,steps in CASES:
        full='演示企业｜'+title+'（虚构测试资料）';doc=Document();paths=[]
        for i,(heading,body) in enumerate(steps,1):
            picture=Image.new('RGB',(1200,620),'#eef3f6');draw=ImageDraw.Draw(picture)
            draw.rectangle((0,0,1200,95),fill='#175d77' if 'EQUIP' in marker else '#8c4e21')
            draw.text((35,24),'演示资料 · 非公司正式制度 · 仅用于软件联调',font=font(32),fill='white')
            draw.text((45,135),title+' / 步骤 '+str(i),font=font(43),fill='#162e3b')
            draw.text((45,215),heading,font=font(36),fill='#264a5d')
            for j in range(0,len(body),25):draw.text((45,295+(j//25)*55),body[j:j+25],font=font(29),fill='#243d49')
            draw.rounded_rectangle((720,475,1145,550),radius=14,fill='#176cce' if 'EQUIP' in marker else '#c26b20')
            draw.text((745,492),'演练步骤 '+str(i)+' / '+str(len(steps)),font=font(28),fill='white')
            draw.text((45,575),marker+' · STEP-'+str(i),font=font(22),fill='#536e7d')
            path=DEST/(marker+'-step-'+str(i)+'.png');picture.save(path);paths.append(path)
            doc.add_heading(full,0);doc.add_paragraph('本资料为虚构演练样本，不构成公司制度，不用于真实审批。标识：'+marker)
            doc.add_heading(str(i)+'. '+heading,1);doc.add_paragraph(body);doc.add_picture(str(path),width=Inches(6))
            if i<len(steps):doc.add_page_break()
        file=DEST/(marker+'.docx');doc.save(file)
        entry=next((e for e in existing if e['title']==full),None)
        if not entry:entry=call('POST','/api/v1/manuals/entries',json={'title':full,'product':'虚构演示环境','version':'demo-v1'})
        eid=entry['id']
        if entry['status']=='draft':
            with file.open('rb') as stream:call('POST',f'/api/v1/manuals/entries/{eid}/files',files={'file':(file.name,stream,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            # Explicitly reviewed image-to-step mapping, rather than claiming
            # arbitrary uploaded screenshots have automatic semantic alignment.
            reviewed=[]
            for i,((heading,body),path) in enumerate(zip(steps,paths),1):
                with path.open('rb') as stream:asset=call('POST',f'/api/v1/manuals/entries/{eid}/files',files={'file':(path.name,stream,'image/png')})
                aid=asset.get('asset_id') or asset.get('id')
                assert aid,asset
                reviewed.append({'order':i,'title':heading,'instruction':f'【虚构演示，非公司制度】{body} 演练标识：{marker}。','asset_ids':[str(aid)],'section_asset_ids':[],'page':i})
            call('PUT',f'/api/v1/manuals/entries/{eid}/steps',json={'steps':reviewed,'groups':[{'id':'demo-procedure','title':full,'start':0,'end':len(reviewed),'confirmed':True}]})
            call('POST',f'/api/v1/manuals/entries/{eid}/publish')
        for _ in range(120):
            entry=call('GET',f'/api/v1/manuals/entries/{eid}')
            if entry.get('index_status')=='indexed':break
            if entry.get('index_status')=='failed':raise RuntimeError('Demo indexing failed')
            time.sleep(2)
        else:raise TimeoutError('Demo indexing timeout')
        result=call('POST','/api/v1/manuals/retrieve',json={'query':title+'的第二步怎么操作？','top_k':5,'filters':{'entry_id':eid}})
        assert marker in json.dumps(result,ensure_ascii=False)
        images=[im for r in result.get('results',[]) for im in r.get('metadata',{}).get('images',[])]
        assert images,'Published procedure did not return its image references'
        proofs=[]
        for image in images:
            preview=backend.get(image['preview_url']);preview.raise_for_status();assert preview.headers.get('content-type','').startswith('image/')
            proofs.append({'asset_id':image['asset_id'],'bytes':len(preview.content),'sha256':hashlib.sha256(preview.content).hexdigest()})
        report['documents'].append({'entry_id':eid,'title':full,'version':'demo-v1','marker':marker,'source_file':str(file),'images_verified':proofs})
        print('PASS published synthetic procedure with image bytes:',title,len(proofs),flush=True)
    binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'));c=client()
    for kind,url in [('agent','/api/v1/agents/'+binding['agent_id']),('pipeline','/api/v1/pipelines/'+binding['pipeline_id'])]:
        cfg=data(c.get(url))[kind]['config'];ai=cfg['ai'] if kind=='pipeline' else cfg;opts=ai['runner_config'][ai['runner']['id']]
        allowed=json.loads(opts['allowed_entry_ids']);opts['allowed_entry_ids']=json.dumps(list(dict.fromkeys(allowed+[d['entry_id'] for d in report['documents']])))
        data(c.put(url,json={'config':cfg}))
    (RUNTIME/'demo-materials.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS both processors authorized for these synthetic fixtures only')

if __name__=='__main__':prepare()
