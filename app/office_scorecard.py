"""Weekly scorecard of the virtual office (owner, 27 Nov 2026: stabilise before new features — measure every department on
real work: how much came in, how much it finished without the owner, where it failed, and what data is missing).

Read-only counts from the office history (office_messages), the WhatsApp work queue (office_inbox, group messages) and the
data the departments depend on. Sent with the Sunday morning briefing; the GM tool office_scorecard answers any time.
"""
import datetime as dt
import re

from app.storage import db

RIYADH = dt.timezone(dt.timedelta(hours=3))
CODE = re.compile(r'نفذ\s+[A-F0-9]{6}')
FAIL = re.compile(r'تعذر|لم أتمكن|ما قدرت|غير متاح|غير مفعّل|لا أملك|خارج صلاحيات|حاول لاحق')


def _q(c, sql, params=()):
    try:
        c.execute('SAVEPOINT score')
        row = c.execute(sql, params).fetchone()
        c.execute('RELEASE SAVEPOINT score')
        return list(row.values())[0] if row else 0
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT score')
        return None


def data(days=7, now=None):
    from app.virtual_office import DEPARTMENTS
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    out = {'days': days, 'depts': [], 'gaps': {}, 'backlog': {}}
    with db() as c:
        rows = []
        try:
            c.execute('SAVEPOINT score')
            rows = c.execute('SELECT department, channel, reply FROM office_messages WHERE created_at >= %s', (since,)).fetchall()
            c.execute('RELEASE SAVEPOINT score')
        except Exception:
            c.execute('ROLLBACK TO SAVEPOINT score')
        for key, d in DEPARTMENTS.items():
            mine = [r for r in rows if r['department'] == key]
            if not mine:
                out['depts'].append({'key': key, 'name': d['name'], 'person': d.get('person') or '', 'total': 0})
                continue
            codes = sum(1 for r in mine if CODE.search(r['reply'] or ''))
            fails = sum(1 for r in mine if FAIL.search(r['reply'] or ''))
            auto = sum(1 for r in mine if r['channel'] in ('واتساب عميل', 'قروب'))
            out['depts'].append({'key': key, 'name': d['name'], 'person': d.get('person') or '', 'total': len(mine),
                                 'from_whatsapp': auto, 'needs_owner': codes, 'failed': fails,
                                 'done_alone': max(0, len(mine) - codes - fails)})
        out['backlog'] = {
            'customers_waiting': _q(c, '''SELECT COUNT(DISTINCT conversation_id) FROM office_inbox WHERE dispatched_at IS NULL
                AND received_at > %s''', (now - dt.timedelta(days=2),)),
            'groups_unanswered': _q(c, '''SELECT COUNT(DISTINCT conversation_id) FROM whatsapp_group_messages WHERE important
                AND answered_at IS NULL AND received_at > %s''', (since,)),
        }
        out['gaps'] = {
            'finance_drafts': _q(c, "SELECT COUNT(*) FROM finance_documents WHERE status IN ('draft','reviewed')"),
            'files_no_phone': _q(c, "SELECT COUNT(*) FROM shipment_files WHERE COALESCE(phone,'')='' AND stage NOT IN ('closed','delivered')"),
            'files_no_eta': _q(c, "SELECT COUNT(*) FROM shipment_files WHERE eta IS NULL AND stage NOT IN ('arrived','released','delivered','closed')"),
            'files_no_hs': _q(c, "SELECT COUNT(*) FROM shipment_files WHERE COALESCE(hs_code,'')='' AND stage NOT IN ('closed','delivered')"),
        }
    return out


def text(days=7, now=None):
    d = data(days, now)
    lines = [f'📊 أداء المكتب الافتراضي — آخر {d["days"]} أيام']
    active = [x for x in d['depts'] if x['total']]
    if not active:
        lines.append('لا يوجد شغل مسجل في المكتب في هذه الفترة.')
    for x in sorted(active, key=lambda x: -x['total']):
        rate = round(100 * x['done_alone'] / x['total']) if x['total'] else 0
        lines.append(f"• {x['person']} ({x['name']}): {x['total']} طلب — منها {x['from_whatsapp']} من واتساب العملاء والقروبات | "
                     f"أنجزه بنفسه {x['done_alone']} ({rate}%) | ينتظر موافقتك {x['needs_owner']} | تعذر {x['failed']}")
    idle = [x['person'] or x['name'] for x in d['depts'] if not x['total']]
    if idle:
        lines.append('بدون شغل: ' + '، '.join(idle))
    b, g = d['backlog'], d['gaps']
    lines.append('')
    lines.append('⏳ المتأخر: ' + f"{b.get('customers_waiting') or 0} محادثة عميل لم تُوزَّع | "
                 f"{b.get('groups_unanswered') or 0} قروب فيه طلب بلا رد")
    lines.append('🧩 بيانات ناقصة تعيق الأقسام: ' + ' | '.join(f'{label} {v}' for label, v in (
        ('قيود مالية غير مرحّلة', g.get('finance_drafts')), ('ملفات شحن بلا رقم تواصل', g.get('files_no_phone')),
        ('ملفات بلا موعد وصول', g.get('files_no_eta')), ('ملفات بلا بند جمركي', g.get('files_no_hs'))) if v is not None))
    lines.append('«أنجزه بنفسه» = رد بدون طلب موافقة وبدون «تعذر»؛ يُراجع بالعيّنة قبل منح أي قسم صلاحية الإرسال المباشر.')
    return '\n'.join(lines)
