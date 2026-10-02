from email.message import EmailMessage
from app.mail_threads import address, message_id, references, headers, select_match

OWN='afaq@shodai.cc'


def message():
    m=EmailMessage();m['From']='Customer <buyer@example.invalid>';m['To']=OWN
    m['Message-ID']='<reply@example.invalid>';m['In-Reply-To']='<sent@shodai.cc>'
    m['References']='<first@shodai.cc> <sent@shodai.cc>';m.set_content('Reply')
    return m


def candidate(**kw):
    return {'id':1,'recipient':'buyer@example.invalid','mail_user_id':7,'opportunity_id':5,'account_id':2,'provider_message_id':'<sent@shodai.cc>',**kw}


def test_exact_headers_and_addresses():
    data=headers(message(),OWN)
    assert data['manual_reply_address']=='buyer@example.invalid'
    assert data['in_reply_to']=='<sent@shodai.cc>'
    assert data['message_references']=='<first@shodai.cc> <sent@shodai.cc>'
    assert address('Name <X@example.invalid>')=='x@example.invalid'
    assert address('a@example.invalid,b@example.invalid') is None
    assert address('x@example.invalid\r\nBcc: stolen@example.invalid') is None


def test_invalid_id_or_thread_metadata_stays_review():
    for field,value in [('Message-ID','bad'),('In-Reply-To','<valid@id> bad'),('References','prefix <valid@id>')]:
        m=message();m.replace_header(field,value)
        assert headers(m,OWN)['manual_reply_address'] is None
    assert message_id('<evil\n@id>') is None
    assert references('<valid@id> bad')==[]
    assert references(' '.join('<'+str(i)+'@id>' for i in range(31)))==[]


def test_reply_to_lists_and_automation_stay_review():
    for field,value in [('Reply-To','other@example.invalid'),('Auto-Submitted','auto-replied'),('List-Id','bulk'),('Return-Path','<>')]:
        m=message();m[field]=value
        assert headers(m,OWN)['manual_reply_address'] is None
    m=message();m.replace_header('From',OWN)
    assert headers(m,OWN)['manual_reply_address'] is None
    m=message();m.replace_header('To','someone@example.invalid')
    assert headers(m,OWN)['manual_reply_address'] is None


def test_unique_thread_sender_and_mailbox_only():
    row,reason=select_match([candidate()], 'buyer@example.invalid',7,'<sent@shodai.cc>')
    assert row['opportunity_id']==5 and reason=='exact_thread'
    assert select_match([], 'buyer@example.invalid',7)[0] is None
    assert select_match([candidate()], 'stranger@example.invalid',7)[0] is None
    assert select_match([candidate()], 'buyer@example.invalid',8)[0] is None
    assert select_match([candidate(mail_user_id=None)], 'buyer@example.invalid',7)[0] is None


def test_ambiguous_and_conflicting_ancestry_stays_review():
    assert select_match([candidate(),candidate(id=2,opportunity_id=6)],'buyer@example.invalid',7)[0] is None
    assert select_match([candidate(),candidate(id=2,recipient='other@example.invalid')],'buyer@example.invalid',7)[0] is None
    assert select_match([candidate(),candidate(id=2)],'buyer@example.invalid',7)[0] is None
    rows=[candidate(),candidate(id=99,provider_message_id='<older@shodai.cc>')]
    assert select_match(rows,'buyer@example.invalid',7,'<sent@shodai.cc>',['<older@shodai.cc>','<sent@shodai.cc>'])[0]['id']==1
    assert select_match(rows,'buyer@example.invalid',7,None,['<older@shodai.cc>','<sent@shodai.cc>'])[0]['id']==1


def test_duplicate_headers_fail_closed():
    from email import message_from_bytes
    import email.policy
    for duplicate in ('Reply-To: buyer@example.invalid\r\nReply-To: other@example.invalid',
                      'In-Reply-To: <a@id>\r\nIn-Reply-To: <b@id>',
                      'References: <a@id>\r\nReferences: <b@id>',
                      'Message-ID: <a@id>\r\nMessage-ID: <b@id>'):
        raw='From: buyer@example.invalid\r\nTo: '+OWN+'\r\n'+duplicate+'\r\n'
        if not duplicate.startswith('Message-ID'):raw+='Message-ID: <reply@id>\r\n'
        msg=message_from_bytes((raw+'\r\nBody').encode(),policy=email.policy.default)
        assert headers(msg,OWN)['manual_reply_address'] is None


def test_message_id_whitespace_normalizes_without_lowercasing_identity():
    assert message_id('  <CaseSensitive@example.invalid>  ')=='<CaseSensitive@example.invalid>'


def prospect_candidate(**kw):
    return candidate(opportunity_id=None, account_id=None, prospect_id=5, **kw)


def test_exact_prospect_thread_without_request_or_account():
    row,reason=select_match([prospect_candidate()], 'buyer@example.invalid',7,'<sent@shodai.cc>')
    assert reason=='exact_thread' and row['prospect_id']==5
    assert row['opportunity_id'] is None and row['account_id'] is None
    rows=[prospect_candidate(),prospect_candidate(id=99,provider_message_id='<older@shodai.cc>')]
    assert select_match(rows,'buyer@example.invalid',7,None,['<older@shodai.cc>','<sent@shodai.cc>'])[0]['id']==1


def test_prospect_thread_keeps_sender_mailbox_and_duplicate_guards():
    for sender,owner in [('stranger@example.invalid',7),('buyer@example.invalid',8)]:
        row,reason=select_match([prospect_candidate()],sender,owner,'<sent@shodai.cc>')
        assert row is None and reason=='sender_or_mailbox_mismatch'
    assert select_match([prospect_candidate(mail_user_id=None)],'buyer@example.invalid',7,'<sent@shodai.cc>')[0] is None
    assert select_match([prospect_candidate(),prospect_candidate(id=2)],'buyer@example.invalid',7,'<sent@shodai.cc>')[1]=='duplicate_thread_identity'


def test_mixed_prospect_request_or_multiple_prospects_stay_review():
    # Equal numeric IDs across the two tables are still different identities.
    rows=[candidate(),prospect_candidate(id=2,provider_message_id='<other@shodai.cc>')]
    assert select_match(rows,'buyer@example.invalid',7,'<sent@shodai.cc>')[1]=='ambiguous_thread'
    rows=[prospect_candidate(),candidate(id=2,opportunity_id=None,account_id=None,
                                       prospect_id=6,provider_message_id='<other@shodai.cc>')]
    assert select_match(rows,'buyer@example.invalid',7,'<sent@shodai.cc>')[1]=='ambiguous_thread'


def test_invalid_prospect_identity_combinations_stay_review():
    for invalid in [candidate(prospect_id=5),candidate(opportunity_id=None,prospect_id=5),
                    candidate(opportunity_id=None,account_id=None),candidate(opportunity_id=None,account_id=None,prospect_id=None)]:
        assert select_match([invalid],'buyer@example.invalid',7,'<sent@shodai.cc>')[1]=='ambiguous_thread'
    # A legacy opportunity without a customer account remains a valid request.
    assert select_match([candidate(account_id=None)],'buyer@example.invalid',7,'<sent@shodai.cc>')[1]=='exact_thread'
