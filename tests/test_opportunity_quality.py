import os
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/unused")
import unittest
from unittest.mock import patch, Mock
import types
from app.opportunity_quality import assess, verify_public_request
from app.intelligence import analyze

class QualityTests(unittest.TestCase):
    def test_false_positives(self):
        cases = [
            ('https://haraj.com.sa/city/الرياض','مطلوب تخليص جمركي','listing'),
            ('https://haraj.com.sa/123/ad','مطلوب مسوق تخليص جمركي بالعمولة','recruitment'),
            ('https://haraj.com.sa/123/ad','نقدم خدمات التخليص الجمركي باسعار تنافسية','provider'),
            ('https://haraj.com.sa/123/ad','احتاج مخلص جمركي العرض محذوف او قديم','closed'),
            ('internal://customer/account/1','شركة استيراد وتصدير','prospect'),
            ('https://www.google.com/maps/place/x','احتاج تخليص جمركي','listing'),
            ('https://example.com/request/1','شركة استيراد وتصدير','unverified'),
        ]
        for url, body, expected in cases:
            with self.subTest(body=body):
                q=assess('مطلوب تخليص جمركي',body,url)
                self.assertEqual(q['kind'],expected)
                self.assertFalse(q['is_request'])
    def test_explicit_buyer(self):
        self.assertTrue(assess('طلب','أحتاج مخلص جمركي لحاوية في جدة','https://example.com/request/1')['is_request'])
    def test_score_cannot_override_evidence(self):
        z=analyze({'score':100,'company_name':'مطلوب تخليص','signal':'مطلوب مسوق تخليص بالعمولة','source_url':'https://example.com/ad/1'})
        self.assertEqual(z['intent'],'Unverified')
        self.assertEqual(z['priority'],'P3')
    def test_live_source_and_destination_gate(self):
        page={'title':'طلب','url':'https://example.com/ad/1','request_text':'أحتاج مخلص جمركي تواصل buyer@example.com','detail_extracted':True}
        with patch('app.discovery.fetch_public',return_value=page):
            self.assertEqual(verify_public_request(page['url'],'buyer@example.com'),page)
            with self.assertRaises(ValueError): verify_public_request(page['url'],'other@example.com')
            page['detail_extracted']=False
            with self.assertRaises(ValueError): verify_public_request(page['url'])
    def test_failure_does_not_become_verified(self):
        with patch('app.discovery.fetch_public',side_effect=RuntimeError('timeout')):
            with self.assertRaises(RuntimeError): verify_public_request('https://example.com/ad/1')
    def test_no_promotion_or_draft_for_directory(self):
        from app.discovery import _promote_signal
        storage = types.ModuleType('app.storage')
        storage.one = Mock(return_value={'id':1,'opportunity_id':None})
        storage.execute = execute = Mock()
        storage.utcnow = Mock()
        with patch.dict('sys.modules', {'app.storage': storage}):
            self.assertIsNone(_promote_signal(1,'شركة',{'url':'internal://customer/account/1','excerpt':'مستورد','score':100}))
            self.assertEqual(execute.call_count,1)
            self.assertIn('UPDATE discovered_signals',execute.call_args.args[0])

if __name__=='__main__': unittest.main()
