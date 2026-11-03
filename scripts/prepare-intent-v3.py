"""Versioned synthetic training corpus. Never consumes employee conversation logs.

Topic families stay in one split. Prior opened acceptance sets are regression
only, never training, development or calibration. Human review remains pending.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'instances/manuals/intent-samples/v3'
sys.path.insert(0,str(ROOT/'apps/backend'))
from app.manuals.intent.types import Axes

# Each list is a distinct subject family, not random paraphrase splitting.
TOPICS={
 'train':{
  'daily':'二进制换算|浏览器缓存|电脑截屏|邮件礼貌表达|番茄钟|透视表|无线信号|压缩包|桌面壁纸|文件扩展名|二维码|英文时态|万用表|图层蒙版|向量乘法|色彩饱和度|远程桌面原理|多因素认证概念|路由器原理|网络延迟',
  'knowledge':'公司补卡审批|公司考勤规则|本公司入职账号|本公司报销要求|我们单位请假手续|公司员工手册规定|公司离职交接|本公司加班申请|本公司打印机配置|公司邮箱权限|公司电脑领用|公司差旅标准|公司试用期考核|公司人事证明|公司门禁办理|公司外出登记|公司转正手续|公司会议室预约|公司行政采购|公司培训报名',
  'images':'AI设计培训现场|入职课程活动|老师授课|员工实操培训|年度团队合影|消防演习现场|公司前台设备|培训签到页面|公司报销操作界面|入职登记界面|员工活动现场|业务培训全景|内部教学现场|公司年会|导师授课现场|内训实训场景|课程投屏现场|公司团建|公司系统操作|培训教室现场',
  'source_file':'公司费用报销规范|入职培训课件|IT入职指引|行政用品申请单|出差申请表|公司请假表|补卡申请说明|员工手册|公司离职交接清单|公司培训回顾|财务报销模板|公司采购单|公司转正评估表|内部权限申请表|公司会议纪要模板|公司资产领用表|内部流程说明书|公司合同审批表|公司人事登记表|内部培训讲义',
 },
 'development':{
  'daily':'等差数列求和|CSV转义规则|音频采样率|浏览器标签分组|键盘盲打练习|电池循环次数|ZIP与RAR区别|网格排版原则|英文被动语态|软件快捷键设置',
  'knowledge':'本公司停车月卡办理|公司孕检请假|公司礼品领用|公司行政值班安排|我们单位访客登记|公司公章借用|公司宿舍申请|本公司交通补贴|本单位借调手续|公司会议保密要求',
  'images':'公司春季趣味运动会|内部手工体验课|公司新人午餐活动|公司读书分享会|内部安全宣讲会|公司颁奖典礼|内部设计讨论会|公司节日布置|内部设备演示会|公司接待大厅',
  'source_file':'公司访客预约单|内部用印登记表|本公司住宿协议|公司停车申请表|内部礼品登记册|本公司值班安排表|公司借调申请表|内部会议保密书|公司补贴申请表|本公司安全讲座课件',
 },
 'calibration':{
  'daily':'正则表达式分组|DHCP租约原理|图片像素密度|热力学温标|文字首行缩进|机械键盘轴体|Excel条件格式|PDF书签|云盘同步原理|数字签名概念|WiFi频段差别|素数判断',
  'knowledge':'公司导师津贴发放|本公司探亲假|公司搬迁物品登记|公司公益假申请|公司快递月结|公司会议餐预订|公司储物柜申请|公司晚归交通报销|公司宠物入楼规定|公司工服尺码更换|公司技术证书补贴|公司海外员工福利',
  'images':'公司公益植树活动|公司搬迁仪式|内部技术沙龙|公司冬至活动|公司志愿者活动|内部软件演示培训|公司优秀员工表彰|公司开工仪式|内部工服展示|公司校招宣讲会|公司公益课堂|公司文化展厅',
  'source_file':'本公司导师津贴申请表|公司搬迁清点表|内部公益活动报名表|公司储物柜借用单|公司工服更换申请表|内部技术沙龙讲义|公司月结快递协议|公司会议用餐申请表|内部证书补贴表|公司晚归交通单|公司海外福利说明|本公司探亲申请单',
 },
 'acceptance':{
  'daily':'等比数列求和|HTTP状态码含义|HSL颜色表示|声速与温度关系|幻灯片母版|触控板手势|Unicode编码|复利计算原理|Word分节符|无损音频格式|蓝牙配对原理|屏幕刷新率',
  'knowledge':'本公司哺乳室使用|公司献血假|公司夜班餐补|本公司海外轮岗|公司心理咨询预约|公司供应商入场|公司失物招领|公司福利体检|公司实习生答辩|公司爱心基金申请|公司环保积分兑换|公司应急联系人变更',
  'images':'公司健康跑活动|公司义卖活动|内部急救课程|公司中秋手作活动|公司年度开放日|公司员工答辩现场|内部健康讲座|公司园区导览|公司音乐交流会|公司绿色办公宣讲|公司校友见面会|公司急救设备培训',
  'source_file':'公司哺乳室预约表|本公司夜班餐补表|公司轮岗登记表|内部心理服务介绍|公司供应商入场须知|公司失物登记表|公司体检项目清单|内部实习答辩模板|公司爱心基金表|公司环保积分手册|公司应急信息更新单|内部急救教学讲义',
 },
}
PATTERNS={
 'daily':['解释一下{t}','请讲讲{t}的通用知识','{t}是什么原理','教我理解{t}','能用简单的话介绍{t}吗','帮我解答一个常识问题：{t}'],
 'knowledge':['{t}怎么办理','帮我查一下{t}的具体规定','{t}需要什么材料','请依据内部资料说明{t}','想了解{t}的要求','你好，{t}该怎么申请'],
 'images':['展示{t}的照片','我想看{t}的现场图片','帮忙找一下{t}的配图','有{t}的现场照片吗','请从知识库调出{t}图片','发几张{t}的照片看看'],
 'source_file':['把{t}源文件给我','请找{t}的原始文件','我想下载{t}的附件','发我{t}的文档模板','能提供{t}的原件吗','需要{t}文件，不要只讲内容'],
}
CLARIFY={
 'train':['这个怎么处理','帮我改一下','给我那个','要哪个好','这是什么','翻译一下','润色这段话','发一下东西','请看看','先处理这个','帮我总结一下','上面那个呢','怎么弄啊','还有这个','帮我看看附件','替我改写','发给我','需要','要','给我原件'],
 'development':['这个说清楚点','替我润色一下','帮我翻译成法语','给我那张吧','前面那份怎么办','我想要它','看看这份附件','请教一个事情','帮忙分析这个','这两项哪个好'],
 'calibration':['右边那个是什么','帮我校对一遍','翻译成日语','给我刚才那个吧','第三段能改吗','这张哪里不对','我该选哪一份','要处理哪个东西','麻烦看下扫描件','把这个总结成两句话','那份发过来吧','帮我改礼貌一点'],
 'acceptance':['背面的说明是什么','帮忙把这段翻译成韩语','请修改一下那段','上面那两份有何差别','附件里的问题怎么办','我应该怎么选这个','把刚才那句话改短','我要第二个吧','那张发来看看','帮我完善那个方案','把扫描件解释一下','那份东西在哪里'],
}
def row(split,family,text,label,**extras):
 scope='general' if label=='daily' else 'unknown' if label=='clarify' else 'company'
 output={'images':'images','source_file':'source_file','clarify':'unknown'}.get(label,'text')
 return {'id':f'v3-{split}-{family}-{abs_hash(text)}','family':family,'text':text,'intent':label,
  'knowledge_scope':scope,'output_kind':output,'needs_clarification':label=='clarify',
  'source_type':'curated_synthetic_scenario','reviewed_by':'agent','human_review':'pending',
  'tags':['clear'] if label!='clarify' else ['boundary'],
  'action_text':{'daily':'解释通用知识','knowledge':'查询公司规定流程','images':'展示现场照片图片','source_file':'下载源文件原件模板','clarify':'需要澄清上下文'}[label],**extras}

def abs_hash(text):
 import hashlib
 return hashlib.sha256(text.encode()).hexdigest()[:10]

def generate():
 OUT.mkdir(parents=True,exist_ok=True)
 for split,groups in TOPICS.items():
  result=[]
  for label,topics in groups.items():
   for i,topic in enumerate(topics.split('|')):
    patterns=PATTERNS[label] if split=='train' else [PATTERNS[label][(i+len(split))%6],PATTERNS[label][(i+len(split)+3)%6]]
    for pattern in patterns:result.append(row(split,topic,pattern.format(t=topic),label))
  for i,text in enumerate(CLARIFY[split]):result.append(row(split,f'{split}-ambiguous-{i}',text,'clarify'))
  # Mixed greeting/company and provided text: topic-disjoint, correct business
  # precedence and data/instruction distinction; no employee text is copied.
  for i,topic in enumerate(groups['knowledge'].split('|')):
   result.append(row(split,topic,f'你好，先解释一下什么是流程，然后查{topic}的内部要求','knowledge',tags=['clear','boundary','mixed']))
   result.append(row(split,topic,f'帮我润色这句通知：请同事按时提交{topic}材料','daily',tags=['clear','boundary','mixed'],action_text='润色已提供文字'))
  # Image attachments are metadata; classification must not imply seeing them.
  for i,topic in enumerate(groups['knowledge'].split('|')[:4]):
   result.append(row(split,topic,f'{topic}的规定请从公司资料查一下','knowledge',attachment_types=['image'],tags=['clear','boundary']))
  if split in ('calibration','acceptance'):
   for i,topic in enumerate(groups['knowledge'].split('|')[:4]):
    history=[{'role':'user','text':f'我想了解{topic}'},{'role':'assistant','text':f'可以查询{topic}的内部资料。'}]
    result.append(row(split,topic,'那具体需要哪些材料？' if split=='acceptance' else '这种情况要走什么手续？','knowledge',history=history,tags=['boundary','multi_turn']))
   for i,topic in enumerate(groups['images'].split('|')[:4]):
    result.append(row(split,topic,'还有现场的图能给我看看吗' if split=='acceptance' else '我想看现场的照片', 'images',history=[{'role':'user','text':f'介绍{topic}'},{'role':'assistant','text':f'刚才依据公司资料介绍了{topic}。'}],tags=['boundary','multi_turn']))
   for i,topic in enumerate(groups['source_file'].split('|')[:4]):
    result.append(row(split,topic,'需要原文件' if split=='acceptance' else '把刚才的源文件发我','source_file',previous_file_offer=True,previous_sources=[{'entry_id':f'00000000-0000-0000-0000-{i+1:012d}','title':topic,'available':True}],tags=['boundary','multi_turn']))
  if split=='train':
   # Old index/calibration are training only. Opened old acceptance is excluded.
   for old_split in ('index','calibration'):
    for line in (ROOT/f'instances/manuals/intent-samples/v2/{old_split}.jsonl').read_text(encoding='utf-8').splitlines():
     old=json.loads(line);old['id']='train-'+old['id'];old['family']='legacy-'+old['family'];old['training_origin']='v2_'+old_split
     result.append(old)
  path=OUT/(split+'.jsonl')
  if path.exists() and path.read_text(encoding='utf-8')!=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in result):
   if split in ('train','development') or (ROOT/'data/manuals/intent/v3/calibration.json').exists():raise RuntimeError('Versioned data already exists with different content')
  path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in result),encoding='utf-8')
  print(split,len(result),flush=True)
 # BM25 uses task examples, excluding clarification and context-only examples.
 train=[json.loads(x) for x in (OUT/'train.jsonl').read_text(encoding='utf-8').splitlines()]
 index=[{**r,'action_text':r.get('action_text') or {'daily':'解释通用知识 润色已提供文字','knowledge':'查询公司规定流程','images':'展示现场照片图片','source_file':'下载源文件原件模板'}[r['intent']]} for r in train if not r['needs_clarification'] and not r.get('history') and not r.get('previous_sources')]
 (OUT/'index.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in index),encoding='utf-8')
 for name in ('train','development','calibration','acceptance'):
  rows=[json.loads(x) for x in (OUT/(name+'.jsonl')).read_text(encoding='utf-8').splitlines()]
  for r in rows:assert Axes(**{k:r[k] for k in ('knowledge_scope','output_kind','needs_clarification')}).intent==r['intent']

if __name__=='__main__':generate()
