"""«افتح فسح» creates a read-only FASAH task on the work computer (reusing the existing runner kind, no runner update),
manager only; tracking read → no billing preparation. Isolated PostgreSQL, nothing sent."""
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app.bootstrap import app  # noqa: F401
    from app import command_agent
    from app.team import ROLE
    from app.storage import db
    assert 'open_fasah' in command_agent.HANDLERS
    token = ROLE.set({'name': 'محمد', 'manager': True})
    out = command_agent.tool_open_fasah(None, {})
    ROLE.reset(token)
    assert 'فتحت فسح على جهاز العمل' in out and 'سجّل دخولك بنفسك' in out, out
    with db() as c:
        task = c.execute('SELECT kind, params_json, created_by FROM runner_tasks ORDER BY id DESC LIMIT 1').fetchone()
    params = json.loads(task['params_json'])
    assert task['kind'] == 'fasah_declarations' and params == {'which': 'import', 'pages': 1, 'track': True}, params
    token = ROLE.set({'name': 'موظف', 'manager': False})
    assert 'للمدير فقط' in command_agent.tool_open_fasah(None, {})
    ROLE.reset(token)


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'open_fasah_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: «افتح فسح» → read-only FASAH task on the work computer, manager only.')


if __name__ == '__main__':
    main()
