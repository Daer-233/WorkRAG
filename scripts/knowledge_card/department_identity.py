"""Extract a staff ID only from a validated DingTalk private-message event."""

import httpx


def trusted_staff_id(source, sender_id, expected_corp_id):
    platform = getattr(source, 'source_platform_object', None)
    incoming = getattr(platform, 'incoming_message', None)
    if incoming is None or not expected_corp_id or not sender_id:
        return None
    staff_id = str(getattr(incoming, 'sender_staff_id', '') or '').strip()
    sender_corp = str(getattr(incoming, 'sender_corp_id', '') or '').strip()
    bot_corp = str(getattr(incoming, 'chatbot_corp_id', '') or '').strip()
    conversation = str(getattr(incoming, 'conversation_type', '') or '')
    if (conversation != '1' or not staff_id or staff_id != str(sender_id)
            or sender_corp != expected_corp_id or bot_corp != expected_corp_id):
        return None
    return staff_id


async def resolve_event_scope(source, sender_id, headers, *, issue_context=False):
    """Send platform-event identity to the authenticated backend for scope resolution."""
    platform = getattr(source, 'source_platform_object', None)
    incoming = getattr(platform, 'incoming_message', None)
    if incoming is None or not sender_id:
        raise ValueError('钉钉员工身份不可用')
    fields = {
        'staff_id': getattr(incoming, 'sender_staff_id', None),
        'sender_id': str(sender_id),
        'sender_corp_id': getattr(incoming, 'sender_corp_id', None),
        'chatbot_corp_id': getattr(incoming, 'chatbot_corp_id', None),
        'conversation_type': str(getattr(incoming, 'conversation_type', '') or ''),
    }
    if any(not isinstance(value, str) or not value for value in fields.values()):
        raise ValueError('钉钉员工身份不完整')
    fields['issue_context'] = issue_context
    async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
        response = await client.post('http://host.docker.internal:8060/api/v1/manuals/internal/departments/resolve',
                                     headers=headers, json=fields)
        response.raise_for_status()
        result = response.json()
    if (type(result.get('department_mapping_complete')) is not bool
            or not isinstance(result.get('entry_ids'), list)):
        raise ValueError('部门范围响应无效')
    return result
