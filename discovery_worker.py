"""Scheduled discovery uses the same qualification and lock as the web process."""
import os
from app.storage import init_db
from app.discovery import run_discovery_cycle


def run():
    init_db(os.getenv('ADMIN_EMAIL', 'admin@afaaqtuwaiq.local'),
            os.getenv('ADMIN_PASSWORD', 'ChangeMe-Now-2026!'))
    summary = run_discovery_cycle()
    print('DISCOVERY_CYCLE', summary, flush=True)
    return summary


if __name__ == '__main__':
    run()
