"""Owner, 24 Nov 2026: the GM must read a short reply as the answer to its own question (real conversation turns),
and must never drop to the legacy «هل تقصد سؤالًا…» reply after tools ran."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATABASE_URL'] = os.environ.get('AFAAQ_TEST_DATABASE_URL') or os.environ.get('DATABASE_URL', '')
os.environ['ANTHROPIC_API_KEY'] = 'synthetic-test-only'


class Conn:
    def execute(self, sql, args=()):
        class R:
            def fetchall(self): return [{'body': 'المدير: الجهة عمران أم عمران (إقبال)؟ وهل نعتمد كشف أكتوبر؟'}]
            def fetchone(self): return None
        return R()


def main():
    from app import command_agent as ca, command_ai
    from app.team import CONTEXT, ROLE
    seen = []

    def model(messages, system):
        seen.append((list(messages), system))
        if len(seen) == 1:
            return {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'noop_tool', 'input': {}}]}
        return {'content': []}
    ca.call_model = model
    ca.HANDLERS['noop_tool'] = lambda c, a: '✅ جهزت رسالة التذكير لقروب سلة الرحائب — للإرسال: نفذ 123456'
    CONTEXT.set({'member': {'name': 'محمد', 'manager': True},
                 'history': [{'command': 'ذكر عمران بالكشف', 'reply': 'الجهة بالضبط: عمران أم عمران (إقبال)؟ وهل نعتمد كشف أكتوبر؟'}]})
    ROLE.set({'name': 'محمد', 'manager': True})
    ca._member = lambda: {'name': 'محمد', 'manager': True}
    reply = ca.run_agent(Conn(), 'ارسلي في قروب سلة الرحايب وعمران المعني هو الموجود في القروب معكم اعتمدي الكشف المرسل لكم')
    messages, system = seen[0]
    assert [m['role'] for m in messages] == ['user', 'assistant', 'user'], messages
    assert 'عمران (إقبال)' in messages[1]['content'] and 'فاعتبرها إجابة' in system and 'تنبيهات أرسلتها' in system
    assert reply and 'نفذ 123456' in reply and 'هل تقصد' not in reply, reply
    print('PASS: GM reads replies in context; tool results are reported, never the legacy clarify line.')


if __name__ == '__main__':
    main()
