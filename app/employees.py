"""Company employees registry. Members added here get the team WhatsApp command lane
(same provider-identity checks as AFAQ_TEAM); never manager rights. Env AFAQ_TEAM stays authoritative."""


def init():
    from app.storage import db
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS team_employees(
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, short TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE, added_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')


def members():
    """Active employees as AFAQ_TEAM-shaped dicts. Fails closed (no members) if storage is unavailable."""
    try:
        from app.storage import rows
        return [{'phone': r['phone'], 'name': r['name'], 'short': r['short'] or r['name'].split()[0], 'role': r['title'], 'manager': False}
                for r in rows('SELECT name,short,phone,title FROM team_employees WHERE active=TRUE ORDER BY id')]
    except Exception:
        return []
