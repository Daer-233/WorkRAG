from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal['daily','knowledge','images','source_file','clarify']
LABELS = ('daily','knowledge','images','source_file','clarify')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Turn(Strict):
    role: Literal['user','assistant']
    text: str=Field(max_length=2000)


class Source(Strict):
    entry_id: UUID
    title: str=Field(max_length=300)
    version: str=Field(default='',max_length=120)
    available: bool=False
    kind: Literal['archived_file','extracted_markdown']='archived_file'


class RouteRequest(Strict):
    text: str=Field(default='',max_length=4000)
    attachment_types: list[Literal['image','file','audio','video']]=Field(default_factory=list,max_length=20)
    history: list[Turn]=Field(default_factory=list,max_length=4)
    previous_sources: list[Source]=Field(default_factory=list,max_length=12)
    previous_file_offer: bool=False


class Decision(Strict):
    intent: Intent | None=None
    method: str
    mode: Literal['off','shadow','on']='shadow'
    has_image: bool=False
    needs_clarification: bool=False
    message: str=''
    reason: str=''
    scores: dict[str,float]=Field(default_factory=dict)
    margin: float | None=None
    config_version: str=''
    elapsed_ms: float=0
    local_elapsed_ms: float=0


def context_text(request):
    # Current text is always retained; only bounded conversational context is added.
    history='\n'.join(f'{t.role}: {t.text[-240:]}' for t in request.history[-4:])
    return f'当前消息：{request.text}\n最近对话：{history}' if history else request.text
