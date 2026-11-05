"""Source-file offers use archived files, never inferred document titles."""
from pathlib import Path

from .isolation import inside_data


def source_file_info(entry):
    raw=entry.get('source_path')
    if not raw:
        return {'available':False}
    try:
        path=inside_data(raw)
        if not path.is_file(): return {'available':False}
    except (OSError,ValueError):
        return {'available':False}
    name=entry.get('source_name') or path.name
    derived=path.suffix.lower()=='.md' and Path(name).name.startswith('MinerU_markdown_')
    return {'available':True,'name':name,'kind':'extracted_markdown' if derived else 'archived_file',
            'offer_text':'需要这份资料的整理稿文件吗？' if derived else '需要这份资料的源文件吗？',
            'attachment_delivery_verified':False}


OFFER_POLICY = (
    '\n源文件提醒规则：回答确实引用本次检索证据，且 source_file.available=true 时，'
    '在答案结尾只询问一次是否需要相应文件；单份可采用 source_file.offer_text，'
    '多份可询问“需要其中哪份资料的源文件或整理稿？”。'
    '整理稿不能冒称原始 PDF/PPT/Word。无证据、繁忙、仅闲聊或没有可用文件时不提醒。'
    '询问阶段只确认需求；不得承诺已经发送、一定能在此会话发送、'
    '已生成下载地址，也不要把本机访问地址当作员工可用链接。'
    '员工明确回复需要后，先确认对应资料；附件发送由会话宿主核实并回报结果，'
    '不编造附件、发送成功或领取途径。'
)
