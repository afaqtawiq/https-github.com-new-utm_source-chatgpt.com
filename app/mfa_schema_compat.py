from app.storage import db

# The shared storage execute() helper appends RETURNING id to INSERTs.
# MFA tables use natural primary keys, so provide a surrogate id for compatibility.
with db() as c:
    c.execute('ALTER TABLE user_mfa ADD COLUMN IF NOT EXISTS id BIGSERIAL')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS user_mfa_id_uidx ON user_mfa(id)')
    c.execute('ALTER TABLE stepup_auth ADD COLUMN IF NOT EXISTS id BIGSERIAL')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS stepup_auth_id_uidx ON stepup_auth(id)')
