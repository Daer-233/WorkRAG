"""Local administration of department mappings and document scopes."""
from pathlib import Path
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.connection import connection
from .isolation import DATA

SCHEMA = Path(__file__).with_suffix('.sql')
NAMES = ('总经办', '发展中心', '营销及品牌部', '硬装事业部', '软装事业部', '供应链中心',
         '人力行政中心', '财务管理中心', '餐饮', '类似艺术公司', '编外组')
router = APIRouter(prefix='/api/v1/manuals/departments')

from .session_memory import authenticate

internal_router = APIRouter(prefix='/api/v1/manuals/internal/departments',
                            dependencies=[Depends(authenticate)])


def enforced():
    try:
        value = json.loads((DATA / 'runtime' / 'department-enforced.json').read_text(encoding='utf-8'))
        return value.get('enabled') is not False
    except FileNotFoundError:
        return False
    except (OSError, ValueError, AttributeError):
        return True


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Mapping(Strict):
    dingtalk_department_id: str | None = Field(default=None, max_length=100)


class ResolveEmployee(Strict):
    staff_id: str = Field(min_length=1, max_length=256)
    sender_id: str = Field(min_length=1, max_length=256)
    sender_corp_id: str = Field(min_length=1, max_length=256)
    chatbot_corp_id: str = Field(min_length=1, max_length=256)
    conversation_type: str = Field(min_length=1, max_length=10)
    issue_context: bool = False


class Grants(Strict):
    target_department_ids: list[UUID] = Field(max_length=100)


class Scope(Strict):
    company_wide: bool = False
    department_ids: list[UUID] = Field(default_factory=list, max_length=100)
    confirmed: bool = False

    @model_validator(mode='after')
    def valid_scope(self):
        if self.confirmed and not (self.company_wide or self.department_ids):
            raise ValueError('确认资料范围时，请选择部门或全公司')
        if self.company_wide and self.department_ids:
            raise ValueError('全公司资料无需另外选择部门')
        if len(set(self.department_ids)) != len(self.department_ids):
            raise ValueError('部门不能重复')
        return self


class BulkScope(Strict):
    entry_ids: list[UUID] = Field(min_length=1, max_length=500)
    scope: Scope

    @model_validator(mode='after')
    def valid_entries(self):
        if len(set(self.entry_ids)) != len(self.entry_ids):
            raise ValueError('资料不能重复')
        return self


def initialize(conn):
    conn.execute(SCHEMA.read_text(encoding='utf-8'))
    for name in NAMES:
        conn.execute('INSERT INTO manual_departments(id,name) VALUES (%s,%s) ON CONFLICT(name) DO NOTHING',
                     (uuid4(), name))


def allowed_entry_ids(conn, dingtalk_department_ids):
    """Return confirmed scopes for verified department IDs; empty identity means company-wide only."""
    rows = conn.execute('''WITH employee_departments AS (
            SELECT id FROM manual_departments WHERE dingtalk_department_id = ANY(%s)
            UNION
            SELECT department_id FROM manual_department_aliases WHERE dingtalk_department_id = ANY(%s)
        ), accessible_departments AS (
            SELECT id FROM employee_departments
            UNION
            SELECT g.target_department_id FROM manual_department_grants g
            JOIN employee_departments e ON e.id=g.department_id
        )
        SELECT DISTINCT s.entry_id FROM manual_entry_scope s
        WHERE s.confirmed AND (s.company_wide OR EXISTS (
            SELECT 1 FROM manual_entry_departments d
            JOIN accessible_departments a ON a.id=d.department_id
            WHERE d.entry_id=s.entry_id))''', (list(dingtalk_department_ids), list(dingtalk_department_ids))).fetchall()
    return {row['entry_id'] for row in rows}


def permitted_for_context(context_id):
    """Re-evaluate current grants for an unexpired Host-issued context."""
    with connection() as conn:
        row = conn.execute('SELECT department_ids FROM manual_department_contexts '
                           'WHERE id=%s AND expires_at>now()', (context_id,)).fetchone()
        if row is None:
            raise ValueError('部门授权上下文已失效，请重新提问')
        return {str(entry_id) for entry_id in allowed_entry_ids(conn, row['department_ids'])}


@internal_router.post('/resolve')
def resolve_employee(payload: ResolveEmployee):
    """Resolve one Host-verified employee, falling back to company-wide scope."""
    from dotenv import dotenv_values
    from .dingtalk_directory import APPROVAL_ENV, DirectoryError, employee_departments

    try:
        expected_corp = dotenv_values(APPROVAL_ENV).get('DINGTALK_CORP_ID') or ''
        if (not expected_corp or payload.conversation_type != '1'
                or payload.staff_id != payload.sender_id
                or payload.sender_corp_id != expected_corp or payload.chatbot_corp_id != expected_corp):
            raise DirectoryError('员工身份无法核实')
        department_ids = employee_departments(payload.staff_id)
        with connection() as conn:
            matched = conn.execute('SELECT dingtalk_department_id FROM manual_departments '
                                   'WHERE dingtalk_department_id = ANY(%s) UNION '
                                   'SELECT dingtalk_department_id FROM manual_department_aliases '
                                   'WHERE dingtalk_department_id = ANY(%s)', (department_ids, department_ids)).fetchall()
            matched_ids = {row['dingtalk_department_id'] for row in matched}
            complete = bool(department_ids) and set(department_ids) <= matched_ids
            accessible = allowed_entry_ids(conn, department_ids if complete else [])
    except DirectoryError:
        complete = False
        with connection() as conn:
            accessible = allowed_entry_ids(conn, [])
    result = {'department_mapping_complete': complete, 'entry_ids': sorted(str(value) for value in accessible)}
    if payload.issue_context:
        context_id = uuid4()
        with connection() as conn:
            conn.execute('DELETE FROM manual_department_contexts WHERE expires_at<=now()')
            conn.execute("INSERT INTO manual_department_contexts(id,department_ids,expires_at) "
                         "VALUES (%s,%s,now()+interval '10 minutes')",
                         (context_id, department_ids if complete else []))
            conn.commit()
        result['context_id'] = str(context_id)
    return result


@router.get('')
def departments():
    with connection() as conn:
        return conn.execute('SELECT * FROM manual_departments ORDER BY name').fetchall()


@router.put('/{department_id}/mapping')
def mapping(department_id: UUID, payload: Mapping):
    value = (payload.dingtalk_department_id or '').strip() or None
    with connection() as conn:
        row = conn.execute('UPDATE manual_departments SET dingtalk_department_id=%s WHERE id=%s RETURNING *',
                           (value, department_id)).fetchone()
        if not row:
            raise ValueError('部门不存在')
        conn.commit()
        return row


@router.get('/{department_id}/grants')
def grants(department_id: UUID):
    with connection() as conn:
        return [r['target_department_id'] for r in conn.execute(
            'SELECT target_department_id FROM manual_department_grants WHERE department_id=%s', (department_id,))]


@router.put('/{department_id}/grants')
def set_grants(department_id: UUID, payload: Grants):
    if department_id in payload.target_department_ids or len(set(payload.target_department_ids)) != len(payload.target_department_ids):
        raise ValueError('本部门默认可访问，请勿重复选择')
    with connection() as conn:
        if not conn.execute('SELECT id FROM manual_departments WHERE id=%s', (department_id,)).fetchone():
            raise ValueError('部门不存在')
        conn.execute('DELETE FROM manual_department_grants WHERE department_id=%s', (department_id,))
        for target in payload.target_department_ids:
            conn.execute('INSERT INTO manual_department_grants VALUES (%s,%s)', (department_id, target))
        conn.commit()
    return {'saved': True}


@router.get('/entries/scopes')
def scopes():
    with connection() as conn:
        return conn.execute('''SELECT e.id AS entry_id, e.title, e.category_id, c.name AS category_name,
            COALESCE(s.confirmed,false) AS confirmed, COALESCE(s.company_wide,false) AS company_wide,
            COALESCE(array_agg(d.department_id) FILTER (WHERE d.department_id IS NOT NULL), ARRAY[]::uuid[]) AS department_ids
            FROM manual_entries e LEFT JOIN manual_categories c ON c.id=e.category_id
            LEFT JOIN manual_entry_scope s ON s.entry_id=e.id
            LEFT JOIN manual_entry_departments d ON d.entry_id=e.id
            GROUP BY e.id,c.name,s.confirmed,s.company_wide ORDER BY e.updated_at DESC''').fetchall()


@router.put('/entries/{entry_id}/scope')
def set_scope(entry_id: UUID, payload: Scope):
    save_scopes([entry_id], payload)
    return {'saved': True}


@router.put('/entries/scopes/batch')
def set_scopes(payload: BulkScope):
    save_scopes(payload.entry_ids, payload.scope)
    return {'saved': True, 'count': len(payload.entry_ids)}


def save_scopes(entry_ids, payload):
    with connection() as conn:
        for entry_id in entry_ids:
            conn.execute('''INSERT INTO manual_entry_scope(entry_id,company_wide,confirmed) VALUES (%s,%s,%s)
                ON CONFLICT(entry_id) DO UPDATE SET company_wide=EXCLUDED.company_wide,confirmed=EXCLUDED.confirmed''',
                (entry_id, payload.company_wide, payload.confirmed))
            conn.execute('DELETE FROM manual_entry_departments WHERE entry_id=%s', (entry_id,))
            for department_id in payload.department_ids:
                conn.execute('INSERT INTO manual_entry_departments VALUES (%s,%s)', (entry_id, department_id))
        conn.commit()
