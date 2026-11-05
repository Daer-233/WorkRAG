"""Read an employee's department IDs using the approval application's credentials."""
from pathlib import Path

import httpx
from dotenv import dotenv_values

APPROVAL_ENV = Path('I:/AI_Develop/py_AI/补贴付款拆分平台_局域网版/.env')


class DirectoryError(RuntimeError):
    """The employee's department membership could not be verified."""


def employee_departments(user_id: str, *, config_path: Path = APPROVAL_ENV, client=None) -> list[str]:
    """Resolve an exact DingTalk user ID, returning all reported department IDs.

    Callers must obtain user_id from a verified platform event, not message text.
    Errors are distinct from an empty department list so callers can fail closed.
    """
    user_id = user_id.strip()
    if not user_id or len(user_id) > 256:
        raise DirectoryError('员工身份无效')
    if not config_path.is_file():
        raise DirectoryError('审批助手通讯录配置不可用')
    config = dotenv_values(config_path)
    app_key = config.get('DINGTALK_CLIENT_ID')
    app_secret = config.get('DINGTALK_CLIENT_SECRET')
    if not app_key or not app_secret:
        raise DirectoryError('审批助手通讯录凭据不完整')

    own_client = client is None
    client = client or httpx.Client(timeout=10, trust_env=False, follow_redirects=False)
    try:
        response = client.post('https://api.dingtalk.com/v1.0/oauth2/accessToken',
                               json={'appKey': app_key, 'appSecret': app_secret})
        response.raise_for_status()
        token = response.json().get('accessToken')
        if not isinstance(token, str) or not token:
            raise DirectoryError('无法获取钉钉通讯录访问凭据')
        response = client.post('https://oapi.dingtalk.com/topapi/v2/user/get',
                               params={'access_token': token}, json={'userid': user_id})
        response.raise_for_status()
        payload = response.json()
        if payload.get('errcode') != 0 or not isinstance(payload.get('result'), dict):
            raise DirectoryError('钉钉通讯录查询失败或员工不在可见范围')
        departments = payload['result'].get('dept_id_list')
        if not isinstance(departments, list) or any(type(item) not in (str, int) or not str(item).isdigit() for item in departments):
            raise DirectoryError('钉钉通讯录部门信息不完整')
        return list(dict.fromkeys(str(item) for item in departments))
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise DirectoryError('钉钉通讯录暂不可用') from None
    finally:
        if own_client:
            client.close()
