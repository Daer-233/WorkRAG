import base64
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workrag_agent.media import prepare_media

EID='00000000-0000-0000-0000-000000000001'
AID='00000000-0000-0000-0000-000000000002'
URL=f'/api/v1/manuals/assets/{AID}?access_token=signed-test'

class Backend:
    def __init__(self,handler=None):
        self.reads=[];self.checks=0
        def serve(request):
            self.reads.append(request.url.path)
            return httpx.Response(200,content=b'PNG fixture',headers={'content-type':'image/png'})
        self.client=httpx.Client(base_url='http://fixed-backend',transport=httpx.MockTransport(handler or serve))
    def document(self,eid,version):
        assert eid==EID and version=='v1'
        self.checks+=1
        return {'assets':[{'asset_id':AID}],'source_name':'demo.docx'}

def images(url=URL):
    return [{'kind':'images','entry_id':EID,'version':'v1','images':[{'preview_url':url,'name':'demo.png'}]}]

def test_image_bytes_and_file_bytes_return_as_native_elements():
    backend=Backend()
    parts,notes=prepare_media(backend,images()+[{'kind':'source_file','entry_id':EID,'version':'v1','name':'demo.docx'}],[EID])
    assert [p['type'] for p in parts]==['image_base64','file_base64']
    assert base64.b64decode(parts[1]['file_base64'])==b'PNG fixture'
    assert parts[1]['file_name']=='demo.docx' and not notes and backend.checks==4

@pytest.mark.parametrize('url',[
    'https://external.invalid/secret','http://127.0.0.1:5300/api/v1/bots','file:///G:/项目/API_Key.txt',
    '/api/v1/manuals/assets/00000000-0000-0000-0000-000000000003?access_token=x',
    f'/api/v1/manuals/assets/{AID}',
])
def test_untrusted_or_cross_document_image_never_downloaded(url):
    backend=Backend()
    with pytest.raises((ValueError,PermissionError)):prepare_media(backend,images(url),[EID])
    assert not backend.reads

def test_media_scope_rechecked_and_duplicate_images_not_sent_twice():
    backend=Backend()
    with pytest.raises(PermissionError):prepare_media(backend,images(),[])
    parts,_=prepare_media(backend,images()*2,[EID])
    assert len(parts)==1 and len(backend.reads)==1

def test_oversized_response_and_redirect_are_rejected():
    for response in [httpx.Response(200,headers={'content-length':str(13*1024*1024)}),
                     httpx.Response(302,headers={'location':'http://external.invalid'})]:
        backend=Backend(lambda request:response)
        with pytest.raises(ValueError):prepare_media(backend,images(),[EID])
