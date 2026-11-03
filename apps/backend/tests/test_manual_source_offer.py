from pathlib import Path

from app.manuals import isolation
from app.manuals.source_offer import source_file_info
from app.manuals.langbot import source_result


def test_offer_requires_existing_archived_file_inside_library(tmp_path,monkeypatch):
    monkeypatch.setattr(isolation,'DATA',tmp_path/'library')
    isolation.DATA.mkdir()
    file=isolation.DATA/'guide.xlsx';file.write_bytes(b'fixture')
    info=source_file_info({'source_path':str(file),'source_name':'报销模板.xlsx'})
    assert info['available'] and info['name']=='报销模板.xlsx'
    assert info['offer_text']=='需要这份资料的源文件吗？'
    assert not info['attachment_delivery_verified']
    assert 'source_path' not in info and str(tmp_path) not in str(info)
    assert source_file_info({})=={'available':False}
    file.unlink()
    assert source_file_info({'source_path':str(file)})=={'available':False}
    outside=tmp_path/'outside.xlsx';outside.write_bytes(b'private fixture')
    assert source_file_info({'source_path':str(outside)})=={'available':False}


def test_mineru_markdown_is_not_offered_as_original_presentation(tmp_path,monkeypatch):
    monkeypatch.setattr(isolation,'DATA',tmp_path)
    file=tmp_path/'source.md';file.write_text('# guide',encoding='utf-8')
    info=source_file_info({'source_path':str(file),'source_name':'MinerU_markdown_fixture.md'})
    assert info['available'] and info['kind']=='extracted_markdown'
    assert info['offer_text']=='需要这份资料的整理稿文件吗？'


def test_offer_metadata_and_policy_are_grounded_in_retrieval_packet():
    info={'available':True,'name':'guide.pdf','kind':'archived_file',
          'offer_text':'需要这份资料的源文件吗？','attachment_delivery_verified':False}
    answer={'entry':{'id':'entry','title':'指南'},'steps':[],'source_file':info}
    result=source_result(answer,'test',{})
    assert result['metadata']['source_file']==info
    assert '只询问一次' in result['content'] and '没有可用文件时不提醒' in result['content']
    assert '发送链路尚未完成验收' in result['content']
    assert source_result({'entry':answer['entry'],'steps':[]},'test',{})['metadata']['source_file']=={'available':False}
