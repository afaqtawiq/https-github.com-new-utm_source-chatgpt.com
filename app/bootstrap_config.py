"""Fail closed when the deployment's administrator bootstrap secret is absent."""
import os


def required_admin_password(environ=None):
    values = os.environ if environ is None else environ
    password = values.get('ADMIN_PASSWORD')
    if not password:
        raise RuntimeError('Administrator bootstrap password is not configured')
    return password
