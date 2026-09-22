from app.marketing_content import email_address, whatsapp_number, select_recipients, message_html, message_text, EMAIL, WEBSITE, PHONE


def test_contacts_are_bounded_normalized_deduplicated_and_suppressed():
    data=[
        dict(source='account:1',name='Company A',email='Sales@Example.com',phone='0501234567',status='lead'),
        dict(source='directory:1',name='Company A duplicate',email='sales@example.com',phone='+966501234567'),
        dict(source='account:2',name='Blocked Company',email='no@example.com',phone='+971501234567',status='unsubscribed'),
        dict(source='directory:2',name='Blocked duplicate',email='no@example.com',phone='+971501234567'),
        dict(source='account:3',name='Bad contacts',email='غير منشور',phone='+966055504207'),
    ]
    selected=select_recipients(data)
    assert len(selected)==2
    assert {r['recipient'] for r in selected}=={'sales@example.com','+966501234567'}
    assert all(r['sources']==['account:1','directory:1'] for r in selected)
    assert len(select_recipients(data,[('email','sales@example.com')]))==1
    assert email_address('victim@example.com\nBcc:another@example.com')==''
    assert whatsapp_number('00971501234567')=='+971501234567'


def test_brochure_contacts_and_optout_are_present_in_both_formats():
    for result in (message_text('https://example.com/b.pdf','https://example.com/stop'),message_html('https://example.com/b.pdf','https://example.com/stop')):
        assert EMAIL in result and WEBSITE in result and PHONE in result
        assert 'https://example.com/b.pdf' in result and 'https://example.com/stop' in result
        assert 'ميناء جدة' in result
