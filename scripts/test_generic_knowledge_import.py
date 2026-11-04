import json

from generic_knowledge_import import prepare_generic


def test_txt_commands_and_menu_are_data_and_stay_in_same_step(tmp_path):
    source=tmp_path/'install.txt'
    source.write_text('## 安装教学\n\n1. 示例命令，不执行\n\n2. 打开菜单\n[1] 安装\n[2] 退出\n\n3. 完成',encoding='utf-8')
    p=prepare_generic(source,title='安装教学')
    assert len(p['groups'])==1 and p['audit']['lost_text_blocks']==0
    assert any('2. 打开菜单\n\n[1] 安装\n\n[2] 退出' in s['instruction'] for s in p['steps'])
    assert all(s['page'] is None for s in p['steps'])


def test_tables_are_atomic_and_only_matching_crops_are_used(tmp_path):
    (tmp_path/'images').mkdir();(tmp_path/'images/a.jpg').write_bytes(b'fixture')
    table='<table><tr><td rowspan="2">职位</td><td>500</td></tr>\n\n<tr><td>400</td></tr></table>'
    source=tmp_path/'policy.md';source.write_text('说明\n\n'+table,encoding='utf-8')
    content=tmp_path/'content.json';content.write_text(json.dumps([{'type':'table','table_body':table,
        'img_path':'images/a.jpg','page_idx':0},{'type':'table','table_body':'不同的表','img_path':'images/not-in-markdown.jpg','page_idx':1}]),encoding='utf-8')
    p=prepare_generic(source,content,title='报销')
    assert p['audit']['tables']==1 and len(p['images'])==1
    assert any(s['instruction']==table and s['page']==1 for s in p['steps'])


def test_cross_page_step_not_cut_at_footer_and_major_heading_is_boundary(tmp_path):
    source=tmp_path/'guide.md'
    source.write_text('## 一、登录\n\n1. 输入账号\n\n1 / 2\n\n继续完成验证\n\n## 2. 完成登录\n\n## 二、打印机使用\n\n查看位置表',encoding='utf-8')
    p=prepare_generic(source,title='IT')
    assert len(p['groups'])==2
    assert any('输入账号' in s['instruction'] and '继续完成验证' in s['instruction'] for s in p['steps'])
    assert p['audit']['lost_text_blocks']==0


def test_ip_addresses_are_not_treated_as_numbered_procedures(tmp_path):
    source=tmp_path/'printers.txt';source.write_text('##打印机地址\n192.0.2.40 1018\n192.0.2.41 二楼',encoding='utf-8')
    p=prepare_generic(source,title='打印机地址')
    assert len(p['steps'])==1 and '1018' in p['steps'][0]['instruction'] and '二楼' in p['steps'][0]['instruction']
