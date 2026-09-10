import re
from app.storage import execute, one, rows, utcnow

def ensure_schema():
    execute("""CREATE TABLE IF NOT EXISTS naqliat_negotiations(
      id BIGSERIAL PRIMARY KEY, load_id BIGINT UNIQUE NOT NULL REFERENCES naqliat_loads(id) ON DELETE CASCADE,
      owner_phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_owner', owner_price DOUBLE PRECISION,
      driver_price DOUBLE PRECISION, initial_message TEXT, last_owner_message TEXT, broadcast_id BIGINT,
      contacted_at TIMESTAMPTZ, replied_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL, last_error TEXT)""")

def owner_prompt(load):
    return ("السلام عليكم، معك فريق آفاق طويق. وصلتنا حمولة من نقليات "
            f"من {load['origin']} إلى {load['destination']}. نرجو تزويدنا بالسعر المطلوب بالريال، "
            "والوزن الدقيق، وموقعي التحميل والتنزيل، وموعد التحميل، وطريقة الدفع. "
            "سنراجع التفاصيل ونعود إليكم دون التزام نهائي.")

def _digits(s): return str(s).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'))
def extract_price(text):
    text = _digits(text or '')
    m = re.search(r'(?:السعر|قيمة|بمبلغ|بـ|ب)(?:\s*[:：]?\s*)([0-9][0-9,\. ]*)\s*(?:ريال|ر\.س|ر\س)?', text, re.I)
    if not m: m = re.search(r'([0-9][0-9,\. ]*)\s*(?:ريال|ر\.س|ر\س)', text, re.I)
    if not m: return None
    try: return float(m.group(1).replace(',','').replace(' ',''))
    except ValueError: return None

async def start_owner_negotiation(load_id):
    ensure_schema(); load=one('SELECT * FROM naqliat_loads WHERE id=?',(load_id,))
    if not load or not load.get('owner_phone'): return
    current=one('SELECT * FROM naqliat_negotiations WHERE load_id=?',(load_id,))
    if current and current.get('status') not in ('contact_failed',): return
    msg=owner_prompt(load)
    if not current:
        execute('INSERT INTO naqliat_negotiations(load_id,owner_phone,initial_message,updated_at) VALUES(?,?,?,?)',(load_id,load['owner_phone'],msg,utcnow()))
    try:
        from app.whatsapp_integration import send_text_message
        await send_text_message(load['owner_phone'],msg)
        execute("UPDATE naqliat_negotiations SET status='awaiting_owner',contacted_at=?,updated_at=?,last_error=NULL WHERE load_id=?",(utcnow(),utcnow(),load_id))
    except Exception as exc:
        execute("UPDATE naqliat_negotiations SET status='contact_failed',updated_at=?,last_error=? WHERE load_id=?",(utcnow(),str(exc)[:500],load_id))

def _draft_broadcast(load, price):
    existing=one("SELECT broadcast_id FROM naqliat_negotiations WHERE load_id=?",(load['id'],))
    if existing and existing.get('broadcast_id'): return existing['broadcast_id']
    candidates=rows("SELECT id,driver_name,whatsapp_phone FROM drivers WHERE offer_consent=1 AND whatsapp_phone IS NOT NULL ORDER BY id")
    valid=[]; seen=set()
    for d in candidates:
        phone=re.sub(r'[\s\-()]','',str(d.get('whatsapp_phone') or ''))
        if phone.startswith('00'): phone='+'+phone[2:]
        if re.fullmatch(r'\+[1-9]\d{7,14}',phone) and phone not in seen: seen.add(phone); valid.append((d,phone))
    if not valid: return None
    message=(f"حمولة جديدة: {load['origin']} → {load['destination']}\n"
             f"الوزن: {load.get('weight_tons') or 'غير محدد'} طن | المركبة: {load.get('vehicle_type') or 'غير محددة'}\n"
             f"السعر المتاح للسائق: {price-150:.0f} ريال\n{load.get('description') or ''}")
    now=utcnow(); bid=execute('INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
        (f'عرض تلقائي لحمولة نقليات #{load["id"]}',message,'draft',len(valid),None,now,now))
    for d,p in valid: execute('INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status) VALUES(?,?,?,?,?) ON CONFLICT(broadcast_id,phone) DO NOTHING',(bid,d['id'],d['driver_name'],p,'pending'))
    return bid

async def process_owner_webhook(payload):
    ensure_schema()
    for entry in payload.get('entry',[]):
      for change in entry.get('changes',[]):
       for msg in (change.get('value') or {}).get('messages',[]):
        if msg.get('type')!='text': continue
        phone='+'+re.sub(r'\D','',str(msg.get('from') or '')); text=msg.get('text',{}).get('body','')
        n=one("SELECT * FROM naqliat_negotiations WHERE owner_phone=? AND status IN ('awaiting_owner','contact_failed') ORDER BY id DESC LIMIT 1",(phone,))
        if not n: continue
        price=extract_price(text); now=utcnow()
        if price is None:
            execute('UPDATE naqliat_negotiations SET last_owner_message=?,updated_at=? WHERE id=?',(text[:3000],now,n['id'])); continue
        load=one('SELECT * FROM naqliat_loads WHERE id=?',(n['load_id'],)); bid=_draft_broadcast(load,price) if price>150 else None
        execute("UPDATE naqliat_negotiations SET owner_price=?,driver_price=?,broadcast_id=?,status=?,last_owner_message=?,replied_at=?,updated_at=? WHERE id=?",(price,max(price-150,0),bid,'awaiting_broadcast_approval' if bid else 'invalid_price',text[:3000],now,now,n['id']))
        if bid:
            try:
                from app.whatsapp_integration import send_text_message
                await send_text_message(phone,'شكرًا، تم استلام التفاصيل وسنعود إليكم بعد المراجعة.')
            except Exception: pass
