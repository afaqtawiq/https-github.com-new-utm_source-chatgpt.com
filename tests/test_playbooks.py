import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import playbooks as pb


def test_all_playbooks_installed_and_found_from_arabic_tasks():
    names = pb.index()
    assert len(names) >= 52 and 'cold-email' in names and 'prospecting' in names and 'afaq-b2b-outreach' in names
    assert pb.choose('اكتبي بريد بارد لشركات الشحن في دبي')[0] == 'cold-email'
    assert 'ads' in pb.choose('خطة إعلانات ممولة على سناب وجوجل')
    assert pb.choose('جهزي عرض باقة تخليص مع خصم')[0] in ('offers', 'pricing')
    assert 'marketing-plan' in pb.choose('خطة تسويق 90 يوم')
    text = pb.answer('ابحثي عن عملاء محتملين')
    assert text.startswith('📘 دليل «prospecting»') and len(text) > 2000
    assert 'cold-email' in pb.answer(name='cold-email')
    assert pb.answer('xyz qqq').startswith('ما لقيت دليلًا')
