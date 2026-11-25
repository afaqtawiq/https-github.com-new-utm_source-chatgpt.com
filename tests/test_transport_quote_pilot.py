"""The 20 attached pilot tests (Afaaq_WhatsApp_Quote_Pilot.zip), unchanged except the import path."""
from datetime import date
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.transport_intake import intake,quote

TODAY=date(2026,11,25)
BASE='عندي حمولة من جدة إلى الرياض، بضاعة: خشب، حاوية ٢٠ قدم، ٢٥ طن، التحميل الخميس، مع رجوع الفارغ، بالرحلة'
R=dict(origin='jeddah',destination='riyadh',equipment='container_20',max_tons=25,empty_return=True,unit='trip',
       cargo='خشب',approved=True,currency='SAR',amount_sar=2000,ref='DEMO20',valid_from=date(2026,11,1),
       valid_until=date(2026,11,30),tax_included=False,charges_terms='سعر وهمي للاختبار')
R40=dict(R,equipment='container_40',amount_sar=2500,ref='DEMO40')
D='internal_draft'; M='need_details'; H='human_review'; X='rate_review'
CASES=[
 ('20ft',[BASE],[R,R40],D,2000),
 ('40ft',[BASE.replace('٢٠','٤٠')],[R,R40],D,2500),
 ('wrong equipment',[BASE],[R40],X,None),
 ('foreign currency',[BASE],[dict(R,currency='AED')],X,None),
 ('unknown currency',[BASE],[dict(R,currency=None)],X,None),
 ('unapproved',[BASE],[dict(R,approved=False)],X,None),
 ('wrong return',[BASE.replace('مع رجوع','بدون رجوع')],[R],X,None),
 ('unknown return',[BASE.replace('مع رجوع الفارغ، ','')],[R],M,None),
 ('wrong unit',[BASE.replace('بالرحلة','بالحاوية')],[R],X,None),
 ('overweight',[BASE.replace('٢٥','٢٧')],[R],X,None),
 ('capacity not cargo weight',[BASE.replace('٢٥','حتى ٢٥')],[R],M,None),
 ('multi turn',BASE.split('، ',1),[R],D,2000),
 ('shipper asks for truck',[BASE.replace('عندي حمولة','نحتاج شاحنة')],[R],D,2000),
 ('carrier offers truck',['عندي شاحنة ٢٥ طن من جدة إلى الرياض'],[R],'carrier',None),
 ('unclear role',['جدة إلى الرياض ٢٥ طن'],[R],'role_review',None),
 ('combined request',[BASE+' ونحتاج تخليص جمركي'],[R],H,None),
 ('two sizes',[BASE+' أو حاوية ٤٠ قدم'],[R],H,None),
 ('route correction',[BASE+' التصحيح إلى الخرج'],[R],H,None),
 ('expired rate',[BASE],[dict(R,valid_until=date(2026,11,24))],X,None),
 ('two conflicting rates',[BASE],[R,dict(R,amount_sar=2200,ref='DEMO_OTHER')],X,None),
]
class Pilot(unittest.TestCase):
    pass
def case(messages,rates,status,amount):
    def test(self):
        result=quote(intake(messages),rates,TODAY)
        self.assertEqual(result['state'],status)
        self.assertEqual(result.get('amount_sar'),amount)
        if status==D:
            self.assertIs(result['send_allowed'],False)
            self.assertTrue(result['rate_ref'].startswith('DEMO'))
        if status==M:
            self.assertEqual(len(result['missing']),1)
    return test
for i,(name,*args) in enumerate(CASES,1):
    setattr(Pilot,'test_%02d_%s'%(i,name.replace(' ','_')),case(*args))


class Integration(unittest.TestCase):
    def test_draft_owner_is_reem_and_never_sendable(self):
        r = quote(intake([BASE]), [R], TODAY)
        self.assertEqual((r['owner'], r['send_allowed']), ('ريم', False))

    def test_non_container_empty_return_is_not_applicable(self):
        msg = 'عندي حمولة من الرياض إلى الدمام، بضاعة: حديد، ستارة، ٢٠ طن، التحميل الخميس، بالرحلة'
        card = intake([msg])
        self.assertEqual(card['state'], 'ready')
        self.assertEqual(card['details']['empty_return'], 'not_applicable')
        cur = dict(R, origin='riyadh', destination='dammam', equipment='curtain', cargo='حديد', empty_return='not_applicable', ref='DEMO_C')
        self.assertEqual(quote(card, [cur], TODAY)['amount_sar'], 2000)
        # «not included» (False) never matches «not applicable».
        self.assertEqual(quote(card, [dict(cur, empty_return=False)], TODAY)['state'], X)

    def test_relevance_gate(self):
        from app.transport_intake import relevant
        self.assertFalse(relevant(['السلام عليكم', 'شكرا']))
        self.assertTrue(relevant(['كم النقل من جدة إلى الرياض']))
