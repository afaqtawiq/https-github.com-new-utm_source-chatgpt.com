"""Signed project material mirror; deterministic, zero-cost caption revisions."""
import hashlib
import hmac
import json
import os
import re
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.storage import db

router = APIRouter()

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def ensure_materials(c):
    c.execute("""CREATE TABLE IF NOT EXISTS shawahid_materials(
        request_id BIGINT PRIMARY KEY REFERENCES zernio_requests(id),
        state JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")

def revise_caption(document, instruction):
    match = re.match(r'^Change the opening of Promotional Caption (\d+) to:\s*["“]([^"”\n]{1,500})["”]\.?(.*)$', instruction.strip(), re.I | re.S)
    if not match:
        raise ValueError('Please specify: Change the opening of Promotional Caption 1 to: “Your new opening.”')
    number, opening, tail = match.groups()
    permitted = ['Keep the affiliate link and disclosure unchanged.', 'Confirm the exact changes recorded and send the revised caption for review.', 'Do not publish.']
    for sentence in permitted:
        tail = tail.replace(sentence, '')
    if tail.strip() or 'http' in opening.lower() or 'affiliate' in opening.lower():
        raise ValueError('These revision instructions need manual review; no material was changed.')
    pattern = r'(?im)^\s*(?:\d+[.)]\s*)?Promotional Caption ' + re.escape(number) + r'\s*\n+'
    headers = list(re.finditer(pattern, document))
    if len(headers) != 1:
        raise ValueError('The requested caption was not found uniquely in the linked materials.')
    start = headers[0].end()
    stop_match = re.search(r'(?m)^\s*\d+[.)]\s+[^\n]+\n', document[start:])
    stop = start + stop_match.start() if stop_match else len(document)
    section = document[start:stop]
    sentence = re.match(r'[^\n]+?[.!?](?=\s|$)', section)
    if not sentence or re.search(r'https?://|affiliate|associate', sentence.group(), re.I):
        raise ValueError('The opening cannot be safely isolated; manual review is needed.')
    new_section = opening + section[sentence.end():]
    revised = document[:start] + new_section + document[stop:]
    if re.findall(r'https?://\S+', revised) != re.findall(r'https?://\S+', document):
        raise ValueError('Link preservation check failed.')
    if len(new_section) > 3400:
        raise ValueError('The revised caption is too long for a single review message.')
    return revised, new_section.strip()

def material_reply(c, request_id, event_id, instruction):
    ensure_materials(c)
    row = c.execute('SELECT state FROM shawahid_materials WHERE request_id=%s FOR UPDATE', (request_id,)).fetchone()
    if not row:
        return 'Revision saved. Project materials are not linked yet; no revised caption has been generated.'
    state = row['state']
    matches = []
    errors = []
    for artifact in state['artifacts']:
        edit = next((e for e in state.get('edits', []) if e['id'] == artifact['id']), None)
        try:
            revised, excerpt = revise_caption(edit['text'] if edit else artifact['text'], instruction)
            matches.append((artifact, revised, excerpt))
        except ValueError as error:
            errors.append(str(error))
    if len(matches) != 1:
        return 'Revision saved for review. ' + (errors[0] if errors else 'No unique editable caption is linked.') + ' No material was changed.'
    artifact, revised, excerpt = matches[0]
    state['edits'] = [e for e in state.get('edits', []) if e['id'] != artifact['id']] + [{
        'id': artifact['id'], 'baseHash': artifact['hash'], 'hash': digest(revised),
        'text': revised, 'eventId': event_id}]
    c.execute('UPDATE shawahid_materials SET state=%s::jsonb,updated_at=NOW() WHERE request_id=%s', (json.dumps(state), request_id))
    return 'Revised caption — for review only:\n\n' + excerpt + '\n\nThe opening was updated. The affiliate link and disclosure are unchanged. Nothing has been published.'

@router.post('/api/shawahid/materials')
async def sync_materials(request: Request):
    raw = await request.body()
    if len(raw) > 1000000:
        return JSONResponse({'error':'Payload too large'}, status_code=413)
    stamp = request.headers.get('x-intake-time', '')
    secret = os.getenv('SHAWAHID_INTAKE_SECRET', '')
    signature = request.headers.get('x-intake-signature', '')
    try:
        fresh = abs(time.time() - int(stamp)) <= 120
    except ValueError:
        fresh = False
    expected = hmac.new(secret.encode(), b'shawahid-materials-v1:' + stamp.encode() + b':' + raw, hashlib.sha256).hexdigest()
    if not secret or not fresh or not hmac.compare_digest(expected, signature):
        return JSONResponse({'error':'Invalid signature'}, status_code=401)
    try:
        incoming = json.loads(raw)
        for key in ('requestId', 'projectId', 'sourceRevision', 'executionVersion'):
            if type(incoming[key]) is not int or incoming[key] < 1:
                raise ValueError()
        artifacts = incoming['artifacts']
        if not isinstance(artifacts, list) or len(artifacts) > 20:
            raise ValueError()
        ids = set()
        for a in artifacts:
            if not isinstance(a['id'], str) or a['id'] in ids or not isinstance(a['text'], str) or len(a['text']) > 100000 or digest(a['text']) != a['hash']:
                raise ValueError()
            ids.add(a['id'])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({'error':'Invalid materials'}, status_code=400)
    with db() as c:
        owner = c.execute("SELECT id FROM zernio_requests WHERE id=%s AND agent='shawahid' FOR UPDATE", (incoming['requestId'],)).fetchone()
        if not owner:
            return JSONResponse({'error':'Request not found'}, status_code=404)
        ensure_materials(c)
        row = c.execute('SELECT state FROM shawahid_materials WHERE request_id=%s FOR UPDATE', (incoming['requestId'],)).fetchone()
        state = row['state'] if row else None
        edits = []
        if state:
            if state['projectId'] != incoming['projectId'] or incoming['sourceRevision'] < state['sourceRevision']:
                return JSONResponse({'error':'Stale or mismatched project'}, status_code=409)
            for edit in state.get('edits', []):
                current = next((a for a in artifacts if a['id'] == edit['id']), None)
                if current and current['hash'] == edit['hash']:
                    continue
                if not current or current['hash'] != edit['baseHash']:
                    return JSONResponse({'error':'Material changed during customer revision; review conflict'}, status_code=409)
                edits.append(edit)
        incoming['edits'] = edits
        c.execute('INSERT INTO shawahid_materials(request_id,state) VALUES(%s,%s::jsonb) ON CONFLICT(request_id) DO UPDATE SET state=EXCLUDED.state,updated_at=NOW()', (incoming['requestId'], json.dumps(incoming)))
    return {'ok':True,'projectId':incoming['projectId'],'edits':edits}
