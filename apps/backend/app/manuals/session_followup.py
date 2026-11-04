"""Resolve an exact document reference at retrieval time, including media and file status."""
import json
from uuid import UUID

from .groups import batches
from .isolation import DATA
from .langbot import busy_result, source_result
from .source_offer import source_file_info


PHOTO_LINKS = DATA / 'session-memory-photo-links.json'
UNAVAILABLE = '上一轮引用的资料或版本当前不可用。请明确指定要查的新资料或版本。'


def notice(message):
    return {'status': 'insufficient_evidence', 'results': [{
        'id': 'session_memory_notice', 'score': 0.0, 'content': message,
        'metadata': {'result_type': 'retrieval_notice'},
    }]}


def published(entry, version):
    return (entry['status'] == 'published' and entry['processing_status'] == 'ready'
            and (entry.get('version') or '') == version)


def linked_photo(entry):
    try:
        link = json.loads(PHOTO_LINKS.read_text(encoding='utf-8')).get(str(entry['id']))
        if link and link['source_version'] == (entry.get('version') or ''):
            return UUID(link['entry_id']), link['version']
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        pass
    return None


def result_for(entry, service):
    return {'entry': service.public(entry), 'source_file': source_file_info(entry), 'steps': []}


def next_step(entry, service, cursor, query):
    steps = entry['data'].get('steps', [])
    index = next((index for index, step in enumerate(steps)
                  if str(step.get('evidence_id')) == str(cursor)), None) if cursor else None
    if index is None or type(steps[index].get('order')) is not int:
        return notice('上一轮没有确认具体步骤。请告诉我你做到第几步或哪项操作。')
    pages = batches(entry)
    current = next((batch for batch in pages if batch['start'] <= index < batch['end']), None)
    target = next(((number, batch) for number, batch in enumerate(pages, 1)
                   if batch['start'] <= index + 1 < batch['end']), None)
    if (not current or not target or target[1]['group']['id'] != current['group']['id']
            or steps[index + 1].get('order') != steps[index]['order'] + 1):
        return notice('当前资料在这个流程中没有明确的下一步，请说明要继续哪项操作。')
    number, batch = target
    answer = service.answer_entry(entry, query, number, 'session_followup', None, True)
    answer['steps'] = [answer['steps'][index + 1 - batch['start']]]
    answer['has_more'] = False
    return {'status': 'ok', 'results': [source_result(answer, query, {})]}


def image_results(service, entry, query):
    results, seen = [], set()
    candidates = [entry]
    related = linked_photo(entry)
    if related and str(related[0]) != str(entry['id']):
        try:
            photo_entry = service.store.get(related[0])
        except ValueError:
            photo_entry = None
        if photo_entry and published(photo_entry, related[1]):
            candidates.insert(0, photo_entry)
    for candidate in candidates:
        for number, batch in enumerate(batches(candidate), 1):
            stored = candidate['data']['steps'][batch['start']:batch['end']]
            if not any(step.get('asset_ids') or step.get('section_asset_ids') for step in stored):
                continue
            answer = service.answer_entry(candidate, query, number, 'session_followup', None, True)
            selected = []
            for step in answer['steps']:
                for field in ('images', 'section_images'):
                    fresh = []
                    for asset in step[field]:
                        if len(seen) < 12 and asset['asset_id'] not in seen:
                            fresh.append(asset)
                            seen.add(asset['asset_id'])
                    step[field] = fresh
                if step['images'] or step['section_images']:
                    selected.append(step)
            if selected:
                answer.update(steps=selected, has_more=False)
                results.append(source_result(answer, query, {}))
            if len(seen) == 12:
                break
        if len(seen) == 12:
            break
    return ({'status': 'ok', 'results': results} if results else
            notice('这份资料及已关联条目当前没有可展示的图片。'))


def retrieve_followup(service, query, filters, top_k):
    if filters.entry_id is None or filters.version is None:
        raise ValueError('会话追问必须指定资料编号和版本')
    try:
        entry = service.store.get(filters.entry_id)
    except ValueError:
        return notice(UNAVAILABLE)
    if not published(entry, filters.version):
        return notice(UNAVAILABLE)

    if filters.followup == 'source_file':
        return {'status': 'ok', 'results': [source_result(result_for(entry, service), query, {})]}
    if filters.followup == 'images':
        return image_results(service, entry, query)
    if filters.followup == 'next_step':
        return next_step(entry, service, filters.cursor, query)

    try:
        answer = service.ask(question=query, entry_id=filters.entry_id, pinned_version=filters.version,
                             source_only=True, evidence_limit=top_k)
    except ValueError as error:
        if '正在处理另一条检索' not in str(error):
            raise
        return busy_result()
    sources = answer.get('sources') or []
    if not sources:
        return notice('所选资料没有足够证据继续回答。请补充你想查的内容。')
    return {'status': 'ok', 'results': [source_result(source, query, {}) for source in sources]}
