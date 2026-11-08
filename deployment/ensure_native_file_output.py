"""Fix SDK 0.7.16 dropping file_base64 in the existing native output path.

This only adds the missing File conversion alongside existing image_base64.
It does not change templates, targets, URL checks or platform credentials.
"""
import subprocess
from install_agent import DOCKER

CODE=r"""
import inspect,json
from pathlib import Path
from langbot_plugin.api.entities.builtin.provider import message
path=Path(inspect.getfile(message));source=path.read_text()
marker='''                elif ce.type == "image_base64":  # base64
'''
addition='''                elif ce.type == "file_base64":  # WorkRAG native output compatibility
                    if ce.file_base64 is not None:
                        mc.append(platform_message.File(base64=ce.file_base64, name=ce.file_name))
'''
changed=False
original=source
for cls in (message.Message,message.MessageChunk):
    method=inspect.getsource(cls._get_content_platform_message_chain)
    if 'elif ce.type == "file_base64"' not in method:
        if method.count(marker)!=1 or source.count(method)!=1:raise RuntimeError('SDK layout changed; refusing to patch')
        source=source.replace(method,method.replace(marker,addition+marker));changed=True
if changed:
    backup=Path('/app/data/workrag-native-file-output-original.py')
    if not backup.exists():backup.write_text(original)
    compile(source,str(path),'exec');path.write_text(source)
print(json.dumps({'changed':changed,'sdk_file_base64_supported':True,'template_changed':False}))
"""

def ensure():
    result=subprocess.run([DOCKER,'exec','-i','workrag-langbot-1','/app/.venv/bin/python','-'],
                          input=CODE,text=True,capture_output=True,check=True)
    print(result.stdout.strip())
    return __import__('json').loads(result.stdout)['changed']

if __name__=='__main__':ensure()
