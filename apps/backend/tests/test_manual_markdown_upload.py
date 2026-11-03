import asyncio
import pytest
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from starlette.datastructures import UploadFile

from app.manuals import api


@pytest.mark.parametrize('name',['existing.md','existing.txt'])
def test_archives_existing_markdown_without_parsing(tmp_path,monkeypatch,name):
    record={'status':'draft'}
    def update(entry_id,**kwargs): record.update(kwargs);return record
    monkeypatch.setattr(api,'DATA',tmp_path)
    monkeypatch.setattr(api,'service',SimpleNamespace(store=SimpleNamespace(get=lambda _:record,update=update),public=lambda r,*_:r))
    uploaded=UploadFile(file=BytesIO(b'# Original Markdown'),filename=name)
    result=asyncio.run(api.upload(uuid4(),uploaded,page=None))
    assert result['source_name']==name
    assert result['processing_status']=='uploaded'
    assert __import__('pathlib').Path(result['source_path']).read_bytes()==b'# Original Markdown'
