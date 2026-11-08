"""Bounded reads of authorized WorkRAG resources for native platform output.

No model-provided host, local path or arbitrary download URL is followed.
Bytes are transient and are never written into LangGraph checkpoints.
"""
import base64
from pathlib import PurePath
from urllib.parse import urlsplit,parse_qs
from uuid import UUID

MAX_BYTES=12*1024*1024
MAX_TOTAL=20*1024*1024
MAX_IMAGES=3


def download(backend,path):
    with backend.client.stream('GET',path,follow_redirects=False) as response:
        if response.status_code!=200: raise ValueError('Resource download failed')
        if int(response.headers.get('content-length','0'))>MAX_BYTES: raise ValueError('Resource is too large')
        content=bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content)>MAX_BYTES: raise ValueError('Resource is too large')
        if not content: raise ValueError('Resource is empty')
        return bytes(content),response.headers.get('content-type','').split(';')[0]


def prepare_media(backend,requests,allowed):
    parts=[];notes=[];seen=set();total=0;image_count=0
    for request in requests:
        eid=str(UUID(request['entry_id']))
        if eid not in allowed: raise PermissionError('Resource is outside the run scope')
        entry=backend.document(eid,request['version'])
        items=[]
        if request['kind']=='source_file':
            items=[('file',f'/api/v1/manuals/entries/{eid}/source',request.get('name') or entry.get('source_name') or '资料文件')]
        elif request['kind']=='images':
            owned={str(a['asset_id']) for a in entry.get('assets',[])}
            for image in request.get('images',[]):
                parsed=urlsplit(str(image.get('preview_url') or ''))
                if parsed.scheme or parsed.netloc: raise PermissionError('Only relative WorkRAG image references are accepted')
                aid=str(UUID(parsed.path.rsplit('/',1)[-1]))
                if parsed.path!=f'/api/v1/manuals/assets/{aid}' or aid not in owned or not parse_qs(parsed.query).get('access_token'):
                    raise PermissionError('Image does not belong to the authorized document')
                items.append(('image',parsed.path+'?'+parsed.query,image.get('name') or '配图'))
        for kind,path,name in items:
            if path in seen: continue
            seen.add(path)
            if kind=='image' and image_count>=MAX_IMAGES:
                if not notes: notes.append('本轮最多返回 3 张图片，更多图片请指定具体步骤。')
                continue
            binary,mime=download(backend,path)
            if kind=='image' and mime not in {'image/png','image/jpeg','image/webp','image/gif'}: raise ValueError('Unsupported image content')
            total+=len(binary)
            if total>MAX_TOTAL: raise ValueError('Attachment batch is too large')
            encoded=base64.b64encode(binary).decode('ascii')
            name=PurePath(str(name).replace('\\','/')).name
            parts.append({'type':'image_base64','image_base64':encoded} if kind=='image' else
                         {'type':'file_base64','file_base64':encoded,'file_name':name})
            if kind=='image':image_count+=1
        # A source may have been revoked while downloading the bytes.
        backend.document(eid,request['version'])
    return parts,notes
