import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workrag_agent.presentation import employee_text,source_values

EID='ff60800a-e910-4d23-92d5-b06e149983ce'


def test_employee_answer_keeps_action_and_hides_source_metadata():
    raw=f'''资料来源：
- 设备借用演练（版本：demo-v1；证据：{EID}）

核对设备编号 DEMO-LAPTOP-008，点击蓝色“确认借用”。
- 适用版本：demo-v1；演练标识：WRAG-DEMO-EQUIP-01
- 证据 ID：{EID}（第2页）
这是虚构演示，不是公司制度。
需要图片或原文件，请回复“图片”或“文件”。'''
    answer=employee_text(raw)
    assert 'DEMO-LAPTOP-008' in answer and '确认借用' in answer
    assert '设备借用演练' in answer and '虚构演示' in answer and '图片' in answer
    assert all(x not in answer for x in [EID,'demo-v1','证据','适用版本','WRAG-DEMO-EQUIP-01'])


def test_metadata_split_across_stream_chunks_never_displays_evidence_or_version():
    raw='资料来源：\n- 设备借用演练（版本：demo-v1；证据：'+EID+'）\n\n核对 DEMO-LAPTOP-008。\n证据 ID：'+EID
    for end in range(1,len(raw)+1):
        answer=employee_text(raw[:end],final=False)
        assert 'demo-v1' not in answer and EID[:8] not in answer
    assert 'DEMO-LAPTOP-008' in employee_text(raw)


def test_internal_image_links_hidden_but_file_name_and_business_versions_preserved():
    text=f'配图如下：\n- [步骤图](http://127.0.0.1:8060/api/v1/manuals/assets/{EID}?access_token=secret)\n安装 Python 3.11。\n文件：设备借用.docx'
    answer=employee_text(text)
    assert 'access_token' not in answer and EID not in answer
    assert 'Python 3.11' in answer and '设备借用.docx' in answer


def test_known_internal_values_hidden_even_in_unexpected_model_wording():
    values=source_values([{'version':'demo-v1','evidence_ids':[EID]}])
    raw='设备 DEMO-LAPTOP-008。资料当前是demo-v1，来源定位 '+EID
    for n in range(1,len(raw)+1):
        text=employee_text(raw[:n],final=False,internal_values=values)
        assert 'demo-v1' not in text and EID not in text
    assert 'DEMO-LAPTOP-008' in employee_text(raw,internal_values=values)
    assert source_values([{'version':'2024','evidence_ids':[]}])==[]
