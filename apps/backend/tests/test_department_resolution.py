from contextlib import contextmanager
from uuid import uuid4

from app.manuals import departments, dingtalk_directory


def employee():
    return departments.ResolveEmployee(staff_id='employee', sender_id='employee',
        sender_corp_id='corp', chatbot_corp_id='corp', conversation_type='1')


def test_unmapped_or_unavailable_directory_uses_only_company_scope(monkeypatch):
    company_entry = uuid4()
    private_entry = uuid4()

    class Rows:
        def fetchall(self):
            return [{'dingtalk_department_id': '1'}]

    class Connection:
        def execute(self, *args):
            return Rows()

    @contextmanager
    def fake_connection():
        yield Connection()

    def allowed(conn, ids):
        return {company_entry, private_entry} if ids else {company_entry}

    monkeypatch.setattr(departments, 'connection', fake_connection)
    monkeypatch.setattr('dotenv.dotenv_values', lambda path: {'DINGTALK_CORP_ID': 'corp'})
    monkeypatch.setattr(departments, 'allowed_entry_ids', allowed)
    monkeypatch.setattr(dingtalk_directory, 'employee_departments', lambda employee: ['1', '2'])
    result = departments.resolve_employee(employee())
    assert result == {'department_mapping_complete': False, 'entry_ids': [str(company_entry)]}

    def fail(employee):
        raise dingtalk_directory.DirectoryError('unavailable')

    monkeypatch.setattr(dingtalk_directory, 'employee_departments', fail)
    assert departments.resolve_employee(employee()) == result


def test_all_mapped_departments_are_used(monkeypatch):
    seen = []

    class Rows:
        def fetchall(self):
            return [{'dingtalk_department_id': '1'}, {'dingtalk_department_id': '2'}]

    class Connection:
        def execute(self, *args):
            return Rows()

    @contextmanager
    def fake_connection():
        yield Connection()

    def allowed(conn, ids):
        seen.extend(ids)
        return set()

    monkeypatch.setattr(departments, 'connection', fake_connection)
    monkeypatch.setattr('dotenv.dotenv_values', lambda path: {'DINGTALK_CORP_ID': 'corp'})
    monkeypatch.setattr(departments, 'allowed_entry_ids', allowed)
    monkeypatch.setattr(dingtalk_directory, 'employee_departments', lambda employee: ['1', '2'])
    result = departments.resolve_employee(employee())
    assert result['department_mapping_complete'] is True
    assert seen == ['1', '2']
