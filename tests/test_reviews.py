import os
from unittest.mock import patch
from app import reviews


def test_review_link_only_google_https():
    with patch.dict(os.environ, {'GOOGLE_REVIEW_URL': 'https://g.page/r/abc123/review'}):
        assert reviews.review_url() and 'g.page' in reviews.line() and 'قوقل' in reviews.after_delivery_text('الحياة')
    for bad in ('', 'http://g.page/r/x', 'https://evil.example/review', 'https://g.page/r/x y'):
        with patch.dict(os.environ, {'GOOGLE_REVIEW_URL': bad}):
            assert reviews.review_url() == '' and reviews.line() == '' and reviews.after_delivery_text() is None
