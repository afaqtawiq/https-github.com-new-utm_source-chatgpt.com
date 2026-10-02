"""Exact public email evidence; never infer a request from a contact address."""
import re

# Match the whole RFC-style local part. A suffix of legal!sales@company.example
# is a different address and must never count as evidence for sales@....
PUBLIC_EMAIL = re.compile(r"(?<![a-z0-9.!#$%&'*+/=?^_`{|}~-])([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,})(?![a-z0-9-]|\.[a-z0-9-])", re.I)


def published_emails(text):
    return {match.group(1).lower().rstrip('.') for match in PUBLIC_EMAIL.finditer(str(text or ''))}
