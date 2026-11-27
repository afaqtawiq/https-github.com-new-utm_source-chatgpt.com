"""Every WhatsApp request goes to the virtual office: private customer chats (office_inbox) and groups (group_dispatch)."""
import datetime as dt
import uuid
from unittest.mock import patch

from app import office_inbox as oi
from app.storage import db, utcnow


def _conv():
    return 'conv-' + uuid.uuid4().hex[:8]


def test_customer_requests_are_kept_small_talk_is_not():
    cid = _conv()
    assert oi.keep('acc', cid, 'm-' + cid + '1', '966500000123', 'محمد', 'كم سعر نقل حاوية 40 من جدة للرياض؟', 0)
    assert not oi.keep('acc', cid, 'm-' + cid + '2', '966500000123', 'محمد', 'شكرا', 0)
    assert oi.keep('acc', cid, 'm-' + cid + '3', '966500000123', 'محمد', '', 2)          # documents
    assert not oi.keep('acc', cid, 'm-' + cid + '1', '966500000123', 'محمد', 'كم سعر نقل؟', 0)  # same message twice


def test_burst_waits_for_quiet_then_goes_to_the_department_owner_only_for_codes():
    cid = _conv()
    old = utcnow() - dt.timedelta(minutes=10)
    oi.keep('acc', cid, 'a-' + cid, '966500000321', 'شركة الندى', 'ابغى سعر نقل سطحة من الدمام للرياض', 0, at=old)
    oi.keep('acc', cid, 'b-' + cid, '966500000321', 'شركة الندى', 'الحمولة 25 طن ضروري', 0, at=old + dt.timedelta(minutes=1))
    bursts = [b for b in oi.pending() if b[0]['conversation_id'] == cid]
    assert len(bursts) == 1 and len(bursts[0]) == 2
    calls, sent = [], []

    def ask(key, request, author, **kw):
        calls.append((key, request))
        return 'طلبت أسعار من 5 سائقين. للإرسال للعميل اكتب: نفذ A1B2C3'

    async def deliver(text):
        sent.append(text)
    with patch('app.virtual_office.ask', side_effect=ask), patch('app.virtual_office.owner_chat', return_value=None), \
            patch('app.owner_briefing.deliver', side_effect=deliver), patch.object(oi, 'pending', return_value=bursts):
        assert oi.run_round() == 1
    assert calls[0][0] == 'transport' and 'الدمام للرياض' in calls[0][1] and 'نفذ' in calls[0][1]
    assert len(sent) == 1 and 'خالد' in sent[0] and 'نفذ A1B2C3' in sent[0]
    with db() as c:
        rows = c.execute('SELECT dept, dispatched_at FROM office_inbox WHERE conversation_id=%s', (cid,)).fetchall()
    assert all(r['dept'] == 'transport' and r['dispatched_at'] for r in rows)
    assert not [b for b in oi.pending() if b[0]['conversation_id'] == cid]   # never twice
    # No code in the department's answer → it stays in the office, no WhatsApp to the owner.
    cid2 = _conv()
    oi.keep('acc', cid2, 'c-' + cid2, '966500000999', '', 'وين وصلت الحاوية MSCU1234565؟', 0, at=old)
    b2 = [b for b in oi.pending() if b[0]['conversation_id'] == cid2]
    with patch('app.virtual_office.ask', return_value='الحاوية في الطريق، الوصول المتوقع 2 ديسمبر.'), \
            patch('app.virtual_office.owner_chat', return_value=None), patch('app.owner_briefing.deliver', side_effect=deliver), \
            patch.object(oi, 'pending', return_value=b2):
        oi.run_round()
    assert len(sent) == 1


def test_recent_message_waits_and_cap_stops():
    cid = _conv()
    oi.keep('acc', cid, 'd-' + cid, '966500000777', '', 'ممكن عرض سعر تخليص؟', 0)   # just now → not yet
    assert not [b for b in oi.pending() if b[0]['conversation_id'] == cid]
    with patch.dict('os.environ', {'OFFICE_INBOX_DAILY_CAP': '0'}), patch('app.virtual_office.ask') as ask, \
            patch.object(oi, 'pending', return_value=[[{'conversation_id': 'x'}]]):
        assert oi.run_round() == 0 and not ask.called


def test_groups_dispatch_answered_requests_too():
    from app import group_dispatch, group_watch
    group_watch.init()
    group_dispatch.init()
    cid = 'grp-' + uuid.uuid4().hex[:8]
    at = utcnow() - dt.timedelta(minutes=10)
    group_watch.store('acc', cid, 'قروب ميناء جدة', 'g1-' + cid, 'incoming', '966511111111', 'عميل', 'ممكن بيان لهالشحنة؟', 1, at)
    with db() as c:
        c.execute('UPDATE whatsapp_group_messages SET answered_at=%s WHERE conversation_id=%s', (at + dt.timedelta(minutes=1), cid))
    bursts = [b for b in group_dispatch.pending() if b[0]['conversation_id'] == cid]
    assert len(bursts) == 1 and bursts[0][0]['answered_at'] is not None
    sent = []

    async def deliver(text):
        sent.append(text)
    with patch('app.virtual_office.ask', return_value='جهزت البيان.') as ask, patch('app.virtual_office.owner_chat', return_value=None), \
            patch.object(group_dispatch, '_read_pdfs', return_value=[]), patch('app.owner_briefing.deliver', side_effect=deliver), \
            patch.object(group_dispatch, 'pending', return_value=bursts):
        assert group_dispatch.run_round() == 1
    assert ask.call_args[0][0] == 'clearance' and 'رد عليه أحد من الفريق' in ask.call_args[0][1]
    assert sent == []   # answered by the team and no code → office only
