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

    async def no_api(code, ref, kind):
        return None

    async def extract(text, ref):
        assert 'MAERSK ELBA' in text and ref == 'HLCUSGN2610BKGW9'
        return {'found': True, 'vessel': 'MAERSK ELBA', 'voyage': '643W', 'pol': 'HAIPHONG', 'pod': 'JEDDAH',
                'eta': '2026-12-02', 'arrived': False, 'containers': ['TGBU5736561']}
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
    async def api(code, ref, kind):
        assert code == 'CMDU'
        return {'found': True, 'eta': '2026-12-05', 'vessel': 'CMA CGM LORENZACCIO', 'carrier': 'CMA CGM'}

    async def boom(url):
        raise AssertionError('page reader must not run')
    monkeypatch.setattr(cta, 'lookup', api)
    monkeypatch.setattr(cta, 'read_page', boom)
    fields, source = asyncio.run(st.api_fields('SHZ8739334', 'bl', 'CMA CGM'))
    assert fields['eta'] == '2026-12-05' and source == 'الربط الرسمي مع CMA CGM'


def test_parse_dcsa_events():
    ev = [
        {'eventType': 'TRANSPORT', 'transportEventTypeCode': 'DEPA', 'eventClassifierCode': 'ACT', 'eventDateTime': '2026-11-21T11:46:00Z',
         'transportCall': {'UNLocationCode': 'MYTPP', 'location': {'locationName': 'Tanjung Pelepas'}, 'exportVoyageNumber': '643W',
                           'vessel': {'vesselName': 'MAERSK ELBA'}}},
        {'eventType': 'EQUIPMENT', 'equipmentEventTypeCode': 'LOAD', 'eventClassifierCode': 'ACT', 'eventDateTime': '2026-11-21T01:27:00Z',
         'equipmentReference': 'TGBU5736561', 'transportCall': {'UNLocationCode': 'MYTPP', 'vessel': {'vesselName': 'MAERSK ELBA'}}},
        {'eventType': 'TRANSPORT', 'transportEventTypeCode': 'ARRI', 'eventClassifierCode': 'EST', 'eventDateTime': '2026-12-02T20:30:00+03:00',
         'transportCall': {'UNLocationCode': 'SAJED', 'location': {'locationName': 'Jeddah'}, 'vessel': {'vesselName': 'MAERSK ELBA'}}},
    ]
    f = cta.parse_dcsa(ev, 'X')
    assert f['found'] and f['eta'] == '2026-12-02' and f['pod'] == 'Jeddah' and not f['arrived']
    assert f['vessel'] == 'MAERSK ELBA' and f['voyage'] == '643W' and f['containers'] == ['TGBU5736561']
    ev.append({'eventType': 'TRANSPORT', 'transportEventTypeCode': 'ARRI', 'eventClassifierCode': 'ACT',
               'eventDateTime': '2026-12-03T06:00:00Z', 'transportCall': {'UNLocationCode': 'SAJED', 'location': {'locationName': 'Jeddah'}}})
    f = cta.parse_dcsa(ev, 'X')
    assert f['arrived'] and f['eta'] == '2026-12-03'
    assert cta.parse_dcsa([], 'X')['found'] is False


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
