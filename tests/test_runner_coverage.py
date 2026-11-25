"""The work computer reports whether a FASAH list read is COMPLETE (reached its date window or the list's last page)
or stopped at its page limit — the live shipment file only trusts complete reads (owner, 25 Nov 2026)."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location('afaq_runner_cov', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)


class FakeList:
    """pages: list of row lists; rows are (ref, number, 'dd/mm/yyyy', details)."""
    def __init__(self, pages, stuck_at=()):
        self.pages, self.at, self.stuck_at = pages, 0, set(stuck_at)

    def rows(self, _page):
        return self.pages[self.at]

    def next_page(self, _page, number):
        """Real runner contract: True = moved, None = no next button (end of list), False = button but page unchanged."""
        if number - 1 in self.stuck_at:
            return False
        if number - 1 < len(self.pages):
            self.at = number - 1
            return True
        return None


def run(pages, since, limit, stuck_at=()):
    fake = FakeList(pages, stuck_at)
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


def test_next_button_present_but_page_unchanged_is_incomplete():
    # page 2 exists (button present) but the list did not move after the click → never «last page».
    rows, cov = run([page(1, 24), page(2, 20), page(3, 3)], '2026-11-04', 20, stuck_at={1})
    assert cov['complete'] is False and cov['end'] == 'page_stuck' and len(rows) == 3


def test_next_page_contract_on_a_real_page_object():
    """next_page itself: no button → None; button clicked but rows unchanged → False; rows changed → True."""
    class Loc:
        def __init__(self, n):
            self.n, self.last = n, self
        def count(self):
            return self.n
        def get_by_text(self, *a, **k):
            return self
        def click(self, **k):
            pass
    class Page:
        def __init__(self, buttons):
            self.buttons = buttons
        def locator(self, *_):
            return Loc(self.buttons)
        def get_by_role(self, *a, **k):
            return Loc(self.buttons)
    task = rn.Task.__new__(rn.Task)
    task.wait = lambda *a: None
    task.list_rows = lambda p: [('R1', '1', '24/11/2026', 'x')]
    assert rn.Task.next_page(task, Page(0), 2) is None
    assert rn.Task.next_page(task, Page(1), 2) is False
    seq = iter([[('R1',)], [('R2',)]])
    task.list_rows = lambda p: next(seq)
    assert rn.Task.next_page(task, Page(1), 2) is True
