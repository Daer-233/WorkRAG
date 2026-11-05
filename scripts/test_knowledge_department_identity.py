from types import SimpleNamespace

from knowledge_card.department_identity import trusted_staff_id


def source(**overrides):
    values = dict(sender_staff_id='employee', sender_corp_id='corp',
                  chatbot_corp_id='corp', conversation_type='1')
    values.update(overrides)
    return SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=SimpleNamespace(**values)))


def test_identity_requires_matching_staff_and_enterprise():
    assert trusted_staff_id(source(), 'employee', 'corp') == 'employee'
    assert trusted_staff_id(source(), 'another', 'corp') is None
    assert trusted_staff_id(source(sender_corp_id='other'), 'employee', 'corp') is None
    assert trusted_staff_id(source(chatbot_corp_id='other'), 'employee', 'corp') is None
    assert trusted_staff_id(source(conversation_type='2'), 'employee', 'corp') is None
    assert trusted_staff_id(source(), 'employee', '') is None
