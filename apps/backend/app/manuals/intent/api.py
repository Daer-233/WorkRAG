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
    return {'configured_mode':cfg['mode'],'effective_mode':'shadow' if cfg['mode']=='on' and not activation_valid(cfg) else cfg['mode'],
            'version':cfg['version'],'calibrated':bool(calibration_valid(cfg)),
            'model_ready':bool(engine.worker and engine.worker.ready),'activation_allowed':activation_valid(cfg)}
