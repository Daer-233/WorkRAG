import os
from langbot_plugin.api.definition.components.page import Page,PageRequest,PageResponse
from workrag_agent.store import Store
from workrag_agent.tools import Backend

class ReviewPage(Page):
    async def handle_api(self,request:PageRequest):
        # Host page-api requires RESOURCE_MANAGE. Workspace is a server deployment binding,
        # never accepted from the iframe request body.
        binding=self.get_installation_binding()
        workspace=getattr(binding,'workspace_uuid',None) if binding else None
        config=self.get_plugin_config()
        if not workspace or workspace!=config.get('workspace'):
            return PageResponse.fail('Workspace is not authorized for this deployment')
        store=Store(config['database_dsn'])
        try:
            if request.endpoint=='/candidates' and request.method=='GET':
                return PageResponse.ok({'candidates':store.candidates(workspace)})
            if request.endpoint=='/review' and request.method=='POST':
                body=request.body or {}
                result=store.review(workspace,body['id'],body['action'],body,Backend('http://host.docker.internal:8060').valid_refs)
                return PageResponse.ok(result)
            return PageResponse.fail('Unknown endpoint')
        except (ValueError,PermissionError,KeyError) as e: return PageResponse.fail(str(e))
        except Exception: return PageResponse.fail('审核服务暂时不可用')
