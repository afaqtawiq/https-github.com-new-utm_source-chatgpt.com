"""Afaq Tuwaiq's official mailbox identity (single source of truth)."""
ADDRESS = 'info@afaqtawiqs.net'
DOMAIN = ADDRESS.split('@', 1)[1]
# Earlier official addresses: their sent history and replies stay recognised as Afaq's own.
PREVIOUS = ('afaq@shodai.cc',)
ALL = (ADDRESS,) + PREVIOUS
MESSAGE_ID_DOMAINS = tuple(a.split('@', 1)[1] for a in ALL)
