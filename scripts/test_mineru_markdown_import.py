import json

import pytest

from mineru_markdown_import import prepare, display_image


def fixture(tmp_path,text):
    folder=tmp_path/'images';folder.mkdir()
    (folder/'a.png').write_bytes(b'image')
    source=tmp_path/'input.md';source.write_text(text,encoding='utf-8')
    content=tmp_path/'content_list.json'
    content.write_text(json.dumps([
        {'type':'text','text':'Q：补卡次数有限定吗？ A：每月补卡机会3次。','page_idx':5},
        {'type':'image','img_path':'images/a.png','page_idx':2},
        {'type':'text','text':'新员工请联系 IT 负责人。','page_idx':8}]),encoding='utf-8')
    return source,content


def test_qa_is_complete_and_image_page_is_not_used_for_text(tmp_path):
    source,content=fixture(tmp_path,'### **人事篇**\n\nQ：补卡次数有限定吗？\n\nA：每月补卡机会3次。\n\n![](images/a.png)\n\n### **IT篇**\n\n新员工请联系 IT 负责人。')
    result=prepare(source,content)
    qa=next(s for s in result['steps'] if s['instruction'].startswith('Q'))
    assert 'A：每月补卡机会3次。' in qa['instruction'] and qa['page']==6
    assert result['images']['images/a.png']['page']==3
    assert result['audit']['lost_text_blocks']==0 and result['audit']['all_images_associated']
    assert [g['title'] for g in result['groups']]==['人事篇','IT篇']
    assert all(g['confirmed'] is False for g in result['groups'])
    assert not result['warnings'] and result['version']==''


def test_missing_or_remote_images_are_not_silently_skipped(tmp_path):
    source,content=fixture(tmp_path,'## 标题\n\n![](images/missing.png)')
    with pytest.raises(ValueError): prepare(source,content)
    source.write_text('![](https://example.com/a.png)',encoding='utf-8')
    with pytest.raises(ValueError): prepare(source,content)
    source.write_text('![](../a.png)',encoding='utf-8')
    with pytest.raises(ValueError): prepare(source,content)


def test_unmatched_edited_text_keeps_unknown_page(tmp_path):
    source,content=fixture(tmp_path,'### 人事篇\n\n这是在 Markdown 中补充的说明，原始解析结果中没有。\n\n![](images/a.png)')
    result=prepare(source,content)
    assert result['steps'][0]['page'] is None
    assert result['images']['images/a.png']['page']==3


def test_oversize_display_copy_preserves_original_and_aspect(tmp_path):
    from PIL import Image
    path=tmp_path/'large.jpg'
    Image.new('RGB',(120,80),'white').save(path)
    original=path.read_bytes()
    target,resized=display_image(path,tmp_path/'display',pixel_limit=1000,max_edge=60)
    assert resized and Image.open(target).size==(60,40) and path.read_bytes()==original
    same,resized=display_image(path,tmp_path/'display')
    assert same==path and not resized


def test_explicit_circled_procedures_are_not_merged(tmp_path):
    source,content=fixture(tmp_path,'### 行政篇\n\n日常办公事务指南\n\n① 滴滴商旅预订\n\n通过钉钉预订机票和酒店\n\n先完成出差审批\n\n② 商务包车申请\n\n填写申请并由负责人审核\n\n③ 外出用车申请\n\n审核通过后自行打车')
    result=prepare(source,content)
    flight=next(s for s in result['steps'] if '机票' in s['instruction'])
    assert '①' in flight['instruction'] and '包车' not in flight['instruction'] and '③' not in flight['instruction']
    assert not result['warnings'] and result['audit']['lost_text_blocks']==0
