"""Tracking through the lines' own pages read by Firecrawl, and the free official DCSA APIs (no network)."""
import asyncio

from app import carrier_tracking_api as cta, shipment_tracking as st

BL_PAGE = '| 45GP | TGBU 5736561 | Vessel departed | 2026-11-21 | TANJUNG PELEPAS |'
CN_PAGE = ('| Loaded | HAIPHONG | 2026-11-06 | 09:12 | NORTHERN GUARD | 644S |\n'
           '| Loaded | TANJUNG PELEPAS | 2026-11-21 | 01:27 | MAERSK ELBA | 643W |\n'
           '| Vessel arrival | JEDDAH | 2026-12-02 | 20:30 | MAERSK ELBA | 643W |')


def test_hapag_bl_reads_the_container_page_then_extracts(monkeypatch):
    urls = []

    async def page(url):
        urls.append(url)
        return BL_PAGE if 'blno=' in url else CN_PAGE

    async def no_api(code, ref, kind, bl_pod=''):
        return None

    async def extract(text, ref, bl_pod=''):
        assert 'MAERSK ELBA' in text and ref == 'HLCUSGN2610BKGW9'
        return {'found': True, 'vessel': 'MAERSK ELBA', 'voyage': '643W', 'pol': 'HAIPHONG', 'pod': 'JEDDAH',
                'eta': '2026-12-02', 'discharged': None, 'containers': ['TGBU5736561']}
    monkeypatch.setattr(cta, 'read_page', page)
    monkeypatch.setattr(cta, 'lookup', no_api)
    monkeypatch.setattr(st, 'extract_page', extract)
    fields, source = asyncio.run(st.api_fields('HLCUSGN2610BKGW9', 'bl', 'Hapag-Lloyd'))
    assert fields['eta'] == '2026-12-02' and fields['vessel'] == 'MAERSK ELBA' and source == 'موقع Hapag-Lloyd'
    assert 'track-by-booking-solution-legacy.html?blno=HLCUSGN2610BKGW9' in urls[0]
    assert urls[1].endswith('track-by-container-solution-legacy.html?container=TGBU5736561')


def test_no_reader_key_falls_back(monkeypatch):
    async def none(*a):
        return None
    monkeypatch.setattr(cta, 'read_page', none)
    monkeypatch.setattr(cta, 'lookup', none)
    assert asyncio.run(st.api_fields('HLCUSGN2610BKGW9', 'bl', 'Hapag-Lloyd')) == (None, 'لا يوجد مفتاح قارئ الصفحات')
    assert asyncio.run(st.api_fields('XYZ1234567', 'bl', ''))[0] is None


def test_official_api_wins_when_it_has_an_eta(monkeypatch):
    async def api(code, ref, kind, bl_pod=''):
        assert code == 'CMDU'
        return {'found': True, 'eta': '2026-12-05', 'vessel': 'CMA CGM LORENZACCIO', 'carrier': 'CMA CGM'}

    async def boom(url):
        raise AssertionError('page reader must not run')
    monkeypatch.setattr(cta, 'lookup', api)
    monkeypatch.setattr(cta, 'read_page', boom)
    fields, source = asyncio.run(st.api_fields('SHZ8739334', 'bl', 'CMA CGM'))
    assert fields['eta'] == '2026-12-05' and source == 'الربط الرسمي مع CMA CGM'


def ev(kind, code, cls, at, place, equip='', vessel='MAERSK ELBA', voyage=''):
    e = {'eventClassifierCode': cls, 'eventDateTime': at,
         'transportCall': {'UNLocationCode': place, 'location': {'locationName': code}, 'exportVoyageNumber': voyage,
                           'vessel': {'vesselName': vessel}}}
    if equip:
        e.update(eventType='EQUIPMENT', equipmentEventTypeCode=kind, equipmentReference=equip)
    else:
        e.update(eventType='TRANSPORT', transportEventTypeCode=kind)
    return e


def test_parse_dcsa_planned_is_not_arrival():
    events = [ev('DEPA', 'Tanjung Pelepas', 'ACT', '2026-11-21T11:46:00Z', 'MYTPP', voyage='643W'),
              ev('LOAD', 'Tanjung Pelepas', 'ACT', '2026-11-21T01:27:00Z', 'MYTPP', equip='TGBU5736561'),
              ev('ARRI', 'Jeddah', 'EST', '2026-12-02T20:30:00+03:00', 'SAJED')]
    f = cta.parse_dcsa(events, 'X', 'JEDDAH, SAUDI ARABIA')
    assert f['found'] and f['eta'] == '2026-12-02' and f['pod'] == 'Jeddah' and f['discharged'] is None
    assert f['vessel'] == 'MAERSK ELBA' and f['voyage'] == '643W' and f['containers'] == ['TGBU5736561']
    info = st.page_info(f, 'Hapag-Lloyd', 'JEDDAH, SAUDI ARABIA')
    assert not info['arrived'] and info['discharged'] is None and 'تقديري' in st.reply_text('X', info)
    assert cta.parse_dcsa([], 'X')['found'] is False


def test_vessel_at_jeddah_is_not_a_kap_container_discharge():
    """Fake data from the review: the vessel calls Jeddah, the container is discharged at King Abdullah Port."""
    events = [ev('ARRI', 'Jeddah', 'ACT', '2026-11-10T06:00:00Z', 'SAJED'),
              ev('DISC', 'Jeddah', 'ACT', '2026-11-10T09:00:00Z', 'SAJED', equip='OTHR1234567'),   # another box
              ev('ARRI', 'King Abdullah Port', 'EST', '2026-11-12T08:00:00Z', 'SAKAC'),
              ev('DISC', 'King Abdullah Port', 'ACT', '2026-11-12T15:00:00Z', 'SAKAC', equip='TGBU5736561')]
    f = cta.parse_dcsa(events, 'X', 'KING ABDULLAH PORT, SAUDI ARABIA')
    assert f['pod'] == 'King Abdullah Port' and f['discharged'] == '2026-11-12'
    info = st.page_info(f, 'Hapag-Lloyd', 'KING ABDULLAH PORT, SAUDI ARABIA')
    assert info['arrived'] and info['discharged'].date().isoformat() == '2026-11-12'
    # Same events, the B/L says Jeddah: the KAP discharge of our box is not «arrived at Jeddah».
    f2 = cta.parse_dcsa(events[:1] + events[2:], 'X', 'Jeddah')
    assert f2['discharged'] is None
    # A page reader that names another port than the B/L never counts as arrival.
    info = st.page_info({'pod': 'Jeddah', 'discharged': '2026-11-10', 'eta': '2026-11-10'}, 'X', 'King Abdullah Port')
    assert not info['arrived'] and 'ميناء التفريغ في البوليصة' in info['pod_mismatch'] and info['pod'] == 'King Abdullah Port'


def test_future_or_missing_discharge_date_is_a_plan():
    info = st.page_info({'pod': 'Jeddah', 'eta': '2099-01-01', 'discharged': '2099-01-01', 'arrived': True}, 'X', 'Jeddah')
    assert not info['arrived'] and info['eta'].date().isoformat() == '2099-01-01'
    info = st.page_info({'pod': 'Jeddah', 'eta': '2026-12-02', 'arrived': True}, 'X', 'Jeddah')  # «arrived» without a date
    assert not info['arrived']
    assert st.port_code('JEDDAH, SAUDI ARABIA') == 'SAJED' and st.port_code('ميناء الملك عبدالله') == 'SAKAC'
    assert st.same_port('Jeddah', '') and not st.same_port('Jeddah', 'Dammam')


def test_save_validates_and_encrypts(monkeypatch):
    import pytest
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', 'k' * 40)
    with pytest.raises(ValueError):
        cta.save('NOPE', 'x' * 20)
    with pytest.raises(ValueError):
        cta.save('FIRECRAWL', 'short')
    cta.save('FIRECRAWL', 'fc-' + 'a' * 30)
    conn = cta._conn('FIRECRAWL')
    assert conn['key'] == 'fc-' + 'a' * 30 and conn['key_enc'] != conn['key'] and 'FIRECRAWL' in cta.configured()
    from app.storage import db
    with db() as c:
        c.execute("DELETE FROM carrier_api_keys WHERE code='FIRECRAWL'")
