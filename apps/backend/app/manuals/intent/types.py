from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Intent = Literal['daily','knowledge','images','source_file','clarify']
LABELS = ('daily','knowledge','images','source_file','clarify')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Axes(Strict):
    model_config=ConfigDict(extra='forbid',strict=True)
    knowledge_scope: Literal['general','company','unknown']
    output_kind: Literal['text','images','source_file','unknown']
    needs_clarification: bool

    @model_validator(mode='after')
    def consistent(self):
        if not self.needs_clarification:
            if self.knowledge_scope=='unknown' or self.output_kind=='unknown':
                raise ValueError('Unresolved factors cannot authorize a route')
            if self.knowledge_scope=='general' and self.output_kind!='text':
                raise ValueError('Only work-library images/files are supported')
        return self

    @property
    def intent(self):
        if self.needs_clarification:return 'clarify'
        if self.output_kind!='text':return self.output_kind
        return 'daily' if self.knowledge_scope=='general' else 'knowledge'


def axes_for_intent(intent):
    if intent=='clarify':return Axes(knowledge_scope='unknown',output_kind='unknown',needs_clarification=True)
    return Axes(knowledge_scope='general' if intent=='daily' else 'company',
                output_kind=intent if intent in ('images','source_file') else 'text',needs_clarification=False)


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
    axes: Axes | None=None
    axis_scores: dict[str,dict[str,float]]=Field(default_factory=dict)
    guard_reasons: list[str]=Field(default_factory=list)


def context_text(request):
    # Current text is always retained; only bounded conversational context is added.
    history='\n'.join(f'{t.role}: {t.text[-240:]}' for t in request.history[-4:])
    return f'当前消息：{request.text}\n最近对话：{history}' if history else request.text
