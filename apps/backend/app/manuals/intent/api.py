from fastapi import APIRouter
from .engine import router as engine
from .settings import activation_valid,calibration_valid,config
from .types import Decision,RouteRequest

router=APIRouter(prefix='/api/v1/manuals/intent')

@router.post('/route',response_model=Decision)
async def route(request:RouteRequest):return await engine.route(request)

@router.get('/status')
def status():
    cfg=config()
    artifact=calibration_valid(cfg)
    return {'configured_mode':cfg['mode'],'effective_mode':'shadow' if cfg['mode']=='on' and not activation_valid(cfg) else cfg['mode'],
            'version':cfg['version'],'sample_set':cfg['sample_set'],'calibrated':bool(artifact),
            'classifier_schema':artifact.get('schema') if artifact else None,
            'nli_factors_validated':bool(artifact and artifact.get('nli_axes_validated')),
            'model_ready':bool(engine.worker and engine.worker.ready),'activation_allowed':activation_valid(cfg)}
