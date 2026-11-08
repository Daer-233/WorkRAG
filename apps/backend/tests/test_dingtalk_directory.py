import httpx
import pytest

from app.manuals.dingtalk_directory import DirectoryError, employee_departments


def test_all_departments_and_exact_user(tmp_path):
    config = tmp_path / '.env'
    config.write_text('DINGTALK_CLIENT_ID=key\nDINGTALK_CLIENT_SECRET=secret\n', encoding='utf-8')
    def handler(request):
        if request.url.host == 'api.dingtalk.com':
            return httpx.Response(200, json={'accessToken': 'token'})
        assert request.read() == b'{"userid":"employee"}'
        return httpx.Response(200, json={'errcode': 0, 'result': {'dept_id_list': [1, 5, 1]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert employee_departments('employee', config_path=config, client=client) == ['1', '5']


def test_directory_failures_do_not_return_departments(tmp_path):
    config = tmp_path / '.env'
    config.write_text('DINGTALK_CLIENT_ID=key\nDINGTALK_CLIENT_SECRET=secret\n', encoding='utf-8')
    def handler(request):
        return httpx.Response(200, json={'accessToken': 'token'} if request.url.host == 'api.dingtalk.com'
                              else {'errcode': 0, 'result': {}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DirectoryError):
            employee_departments('employee', config_path=config, client=client)
