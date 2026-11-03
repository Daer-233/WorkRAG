"""Native DingTalk editorData template; cloud import remains a manual acceptance gate."""
import json


def node(kind, id, props=None, children=None):
    result = {'componentName':kind,'id':id,'props':props or {},'hidden':False,
              'isLocked':False,'condition':True,'conditionGroup':'','title':id}
    if children is not None: result['children'] = children
    return result


def visible(variable):
    return {'type':'dynamicVisible','value':True,'valueType':'variable',
            'variable':variable,'variableType':'global','condition':{'op':'and','conditions':[]}}


def string(value):
    return {'type':'dynamicString','content':value,'i18n':False}


def markdown(id, variable):
    return node('MarkdownBlock',id,{'mdVer':0,'content':{'type':'variableValue','variable':variable,
        'variableType':'global','varType':'markdown'},'isStreaming':False,'marginTop':6,'marginBottom':6,
        'marginLeft':12,'marginRight':12})


def collapse(id,title,children,*,opened=False,visibility=None):
    props = {'id':string(id),'title':string(title),'contentVisible':opened,
             'marginLeft':12,'marginRight':12,'marginTop':8,'marginBottom':8}
    if visibility: props['visible'] = visible(visibility)
    return node('CollapsePanel',id,props,children)


def image(index,prefix):
    localized = {'defaultLang':'zh_Hans','i18n':False,'content':{'zh_Hans':{
        'type':'dynamicImage','valueType':'variable','variable':f'image_{index}',
        'variableType':'global','value':''}}}
    return node('Image',f'{prefix}_image_{index}',{
        'images':localized,'darkModeImages':localized,'single':True,
        'width':{'type':'dynamicWidth','valueType':'fixed','value':96,'variableType':'global','variable':'','full':False,'adaptive':False},
        'height':{'type':'dynamicWidth','valueType':'fixed','value':64,'variableType':'global','variable':'','full':False,'adaptive':False},
        'scaleType':'fitCenter','imageType':'adaptiveSize','adaptiveSize':False,'fixedRatio':False,
        'hoverText':{'type':'dynamicString','variableType':'global','variable':f'image_name_{index}','content':'','i18n':False},
        'enablePreview':True,'visible':visible(f'image_visible_{index}'),
        'marginLeft':0,'marginRight':8,'marginTop':4,'marginBottom':4})


def row(start,prefix):
    cells = [node('Grid',f'{prefix}_cell_{i}',{'direction':'vertical','isAutoWidth':False,'width':33.333,
        'isFixedWidth':False,'isAutoHeight':True,'childGravity':'leftTop','visible':visible(f'image_visible_{i}')},
        [image(i,prefix)]) for i in range(start,start+3)]
    return node('Grid',f'{prefix}_row_{start}',{'direction':'horizontal','isAutoHeight':True,
        'isAutoWidth':True,'isFixedWidth':False,'childGravity':'leftTop','marginLeft':0,'marginRight':0},cells)


def build():
    variables = {'status':'string','answer':'markdown','notice':'markdown','flowStatus':'string',
        'imagesTitle':'string','moreImagesTitle':'string','hasImages':'string',
        'hasMoreImages':'string','hasSources':'string','images':'array','sources':'array','imagesNote':'markdown'}
    for i in range(12):
        variables.update({f'image_{i}':'string',f'image_name_{i}':'string',f'image_visible_{i}':'string',f'source_visible_{i}':'string',
            f'source_title_{i}':'markdown',f'source_location_{i}':'markdown',f'source_excerpt_{i}':'markdown'})
    states = []
    for status in (1,2,3,4,5):
        prefix = f's{status}'
        photos = collapse(prefix+'_photos','相关图片',[row(0,prefix),
            collapse(prefix+'_more','查看全部图片',[row(i,prefix) for i in (3,6,9)],visibility='hasMoreImages')],
            opened=True,visibility='hasImages')
        photos['props']['title'] = {'type':'dynamicString','variableType':'global','variable':'imagesTitle','content':'相关图片','i18n':False}
        photos['children'][1]['props']['title'] = {'type':'dynamicString','variableType':'global','variable':'moreImagesTitle','content':'查看全部','i18n':False}
        photos['children'].append(markdown(prefix+'_images_note','imagesNote'))
        citations = []
        for i in range(12):
            citations.append(node('AICardContent',f'{prefix}_source_{i}',{'visible':visible(f'source_visible_{i}')},[
                markdown(f'{prefix}_source_title_{i}',f'source_title_{i}'),
                markdown(f'{prefix}_source_location_{i}',f'source_location_{i}'),
                collapse(f'{prefix}_source_quote_{i}','查看引用原文',[
                    markdown(f'{prefix}_source_excerpt_{i}',f'source_excerpt_{i}')])]))
        sources = collapse(prefix+'_sources','依据',citations,opened=True,visibility='hasSources')
        states.append(node('AICardStatusContainer',prefix,{'status':status,'enableCollapse':False,
            'autoFoldConfig':{'needFold':False,'heightLimit':480,'foldStatusLocalDataKey':'_cardFold'}},[
            node('AICardContent',prefix+'_content',{},[
                node('BaseText',prefix+'_title',{'text':string('工作知识助手'),'fontSize':16}),
                markdown(prefix+'_status','status'),markdown(prefix+'_answer','answer'),photos,sources,
                markdown(prefix+'_notice','notice')])]))
    names = ('AICardContainer','AICardStatusContainer','AICardContent','BaseText','MarkdownBlock','Grid','Image','CollapsePanel')
    editor = {'schemaVersion':'3.0.0','schema':{'config':None,'componentsMap':[
        {'package':'@ali/dxComponent','version':'1.0.0','exportName':n,'main':'./src/index.tsx',
         'destructuring':False,'subName':'','componentName':n} for n in names],
        'componentsTree':[node('AICardContainer','root',{'enableTitle':False,
            'enablePending':True,'enableWriting':True,'enableDoing':True,'enableFailed':True,
            'flowStatusVar':{'type':'variableValue','variableType':'global','variable':'flowStatus'},
            'cardSizeMode':'adaptive','cardSizeWidthMode':'adaptive','cardSizeHeightMode':'adaptive'},states)]},
        'mockData':{},'renderContext':{},'editVersion':1,'customWidgetInfo':'','useCustomWidgetInfo':False,
        'variableList':[{'id':k,'name':k,'type':v,'private':False,'editorVarType':'variables','disabled':False} for k,v in variables.items()],
        'formList':[],'customContextList':[],'expList':[],'localList':[],'hsfList':[],'lwpList':[],
        'pageData':{},'extension':{'extendType':'AI','aiStatusList':[1,2,3,4,5],'fileTypeList':[]}}
    return {'editorData':json.dumps(editor,ensure_ascii=False),'widgetInfo':'','type':'im','mode':'card'}
