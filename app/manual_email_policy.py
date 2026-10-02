"""The owner's narrow fresh-code exception for manual official email sends.

This does not grant permission, approve content, waive MFA enrollment, or alter
sessions. Callers must keep those checks and the one-attempt send claim.
"""
import re


def is_manual_outbound_send(method, path):
    return method == 'POST' and bool(re.fullmatch(r'/outbound/[1-9][0-9]*/send', path or ''))


def official_manual_send_without_stepup(method, path, selected):
    return bool(is_manual_outbound_send(method, path) and selected
                and selected.get('provider') == 'spacemail'
                and selected.get('sender_email') == 'afaq@shodai.cc'
                and selected.get('status') == 'connected')
