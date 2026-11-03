"""Honor explicitly selected job models even when resuming a saved thread.

Codex otherwise restores the saved model/effort over app-server startup defaults.
The default installer retains the earlier Luna scope; the work-assistant daemon
explicitly selects Terra. No permission or tool fields are touched.
"""
def install(client_class, allowed_models=('gpt-6-luna',)):
    if getattr(client_class,'_work_luna_model_installed',False): return
    initialize=client_class.initialize
    request=client_class.request

    async def initialized(self):
        await initialize(self)
        result=await request(self,'config/read',{'includeLayers':False})
        config=result.get('config',{})
        if config.get('model') in allowed_models:
            self._work_luna_model=config['model']
            self._work_luna_effort=config.get('model_reasoning_effort',config.get('modelReasoningEffort'))

    async def requested(self,method,params=None):
        if method in ('thread/start','thread/resume') and getattr(self,'_work_luna_model',None):
            params=dict(params or {})
            params['model']=self._work_luna_model
            effort=getattr(self,'_work_luna_effort',None)
            if effort:
                params['config']={**(params.get('config') or {}),'model_reasoning_effort':effort}
        return await request(self,method,params)

    client_class.initialize=initialized
    client_class.request=requested
    client_class._work_luna_model_installed=True
