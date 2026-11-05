"""Map uniquely named company departments and descendants from DingTalk."""
import argparse
from pathlib import Path

import httpx
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / 'instances/manuals/.env', override=True)

from app.db.connection import connection
from app.manuals.departments import NAMES, initialize
from app.manuals.dingtalk_directory import APPROVAL_ENV


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    config = dotenv_values(APPROVAL_ENV)
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.post('https://api.dingtalk.com/v1.0/oauth2/accessToken',
            json={'appKey': config['DINGTALK_CLIENT_ID'], 'appSecret': config['DINGTALK_CLIENT_SECRET']})
        response.raise_for_status()
        token = response.json()['accessToken']

        def children(parent):
            response = client.post('https://oapi.dingtalk.com/topapi/v2/department/listsub',
                                   params={'access_token': token}, json={'dept_id': int(parent)})
            response.raise_for_status()
            value = response.json()
            if value.get('errcode') != 0 or not isinstance(value.get('result'), list):
                raise RuntimeError('钉钉部门列表不可用，未保存任何映射')
            return value['result']

        top = children(1)
        roots = {}
        for name in NAMES:
            matches = [item for item in top if item.get('name') == name]
            if len(matches) != 1:
                raise RuntimeError('部门名称未唯一匹配：' + name)
            roots[name] = str(matches[0]['dept_id'])
        descendants = {}
        for name, root_id in roots.items():
            pending = [root_id]
            seen = set()
            while pending:
                current = pending.pop()
                if current in seen or (current in descendants and descendants[current] != name):
                    raise RuntimeError('钉钉部门树存在重复或循环，未保存映射')
                seen.add(current)
                descendants[current] = name
                pending.extend(str(item['dept_id']) for item in children(current))
                if len(descendants) > 10000:
                    raise RuntimeError('部门数量超过限制，未保存映射')

    if options.apply:
        with connection() as conn:
            initialize(conn)
            rows = conn.execute('SELECT id,name,dingtalk_department_id FROM manual_departments').fetchall()
            by_name = {row['name']: row for row in rows}
            for name, root_id in roots.items():
                previous = by_name[name]['dingtalk_department_id']
                if previous and previous != root_id:
                    raise RuntimeError('已有部门映射与钉钉不一致：' + name)
                conn.execute('UPDATE manual_departments SET dingtalk_department_id=%s WHERE id=%s',
                             (root_id, by_name[name]['id']))
            for identifier, name in descendants.items():
                owner = by_name[name]['id']
                existing = conn.execute('SELECT department_id FROM manual_department_aliases '
                                        'WHERE dingtalk_department_id=%s', (identifier,)).fetchone()
                if existing and existing['department_id'] != owner:
                    raise RuntimeError('已有子部门映射与钉钉不一致')
            conn.execute('DELETE FROM manual_department_aliases WHERE department_id = ANY(%s)',
                         ([by_name[name]['id'] for name in roots],))
            for identifier, name in descendants.items():
                owner = by_name[name]['id']
                conn.execute('INSERT INTO manual_department_aliases VALUES (%s,%s) ON CONFLICT DO NOTHING',
                             (identifier, owner))
            conn.commit()
    print(f"{'saved' if options.apply else 'checked'}: {len(roots)} departments, {len(descendants)} mapped nodes")


if __name__ == '__main__':
    main()
