"""The work computer reports whether a FASAH list read is COMPLETE (reached its date window or the list's last page)
or stopped at its page limit — the live shipment file only trusts complete reads (owner, 25 Nov 2026)."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location('afaq_runner_cov', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)


class FakeList:
    """pages: list of row lists; rows are (ref, number, 'dd/mm/yyyy', details)."""
    def __init__(self, pages):
        self.pages, self.at = pages, 0

    def rows(self, _page):
        return self.pages[self.at]

    def next_page(self, _page, number):
        if number - 1 < len(self.pages):
            self.at = number - 1
            return True
        return False


def run(pages, since, limit):
    fake = FakeList(pages)
    task = rn.Task.__new__(rn.Task)
    task.list_rows, task.next_page = fake.rows, fake.next_page
    rows = rn.Task.collect(task, None, since, limit)
    return rows, task.coverage


def page(n, day):
    return [(f'R{n}{i}', f'7{n}{i:04d}', f'{day:02d}/11/2026', 'تحت المعالجة') for i in range(3)]


def test_reaching_the_date_window_is_complete():
    _, cov = run([page(1, 24), page(2, 20), page(3, 3)], '2026-11-04', 20)
    assert cov['complete'] is True and cov['end'] == 'since'


def test_last_page_of_the_list_is_complete():
    _, cov = run([page(1, 24), page(2, 20)], '2026-11-04', 20)
    assert cov['complete'] is True and cov['end'] == 'last_page'


def test_stopping_at_the_page_limit_is_incomplete():
    rows, cov = run([page(1, 24), page(2, 20), page(3, 18), page(4, 3)], '2026-11-04', 2)
    assert cov['complete'] is False and cov['end'] == 'page_limit' and len(rows) == 6


def test_party_read_whose_filter_failed_is_never_complete(tmp_path):
    task = rn.Task.__new__(rn.Task)
    task.params, task.dir = {'which': 'import', 'party': 'سلة', 'since': '2026-11-04'}, tmp_path
    fake = FakeList([page(1, 24), page(2, 3)])
    task.list_rows, task.next_page = fake.rows, fake.next_page
    task.fasah_list = lambda which: type('P', (), {'url': 'https://fasah.zatca.gov.sa/list'})()
    task.filter_party = lambda page, party, which: False          # the importer filter could not be applied
    task.step = lambda *a, **k: None
    task.upload = lambda path, url: True
    assert rn.Task.do_fasah_declarations(task) is True
    cov = task.result['coverage']
    assert cov['complete'] is False and cov['party'] == 'سلة' and cov['which'] == 'import'
