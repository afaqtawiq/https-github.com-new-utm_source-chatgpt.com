"""Read-only Runway Developer API boundary. No generation or billing methods."""
import httpx

ORGANIZATION_URL = 'https://api.dev.runwayml.com/v1/organization'
API_VERSION = '2024-11-06'


class RunwayError(ValueError):
    pass


def organization_balance(key):
    """Return only the validated balance; never return upstream bodies or secrets."""
    try:
        # Fixed destination, no redirects, retries, proxy environment, or paid calls.
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            response = client.get(ORGANIZATION_URL, headers={
                'Authorization': 'Bearer ' + key, 'X-Runway-Version': API_VERSION})
        if response.status_code in (401, 403):
            raise RunwayError('رفض Runway صلاحية المفتاح. راجع مفتاح مشروع Developer API.')
        if response.status_code == 429:
            raise RunwayError('بلغ فحص Runway حد الطلبات. حاول لاحقًا؛ لم يبدأ أي توليد.')
        if response.status_code != 200:
            raise RunwayError('تعذر فحص اتصال Runway. لم يبدأ أي توليد أو شراء رصيد.')
        data = response.json()
        balance = data.get('creditBalance') if isinstance(data, dict) else None
        # bool is an int in Python; reject it and malformed/nonfinite/negative data.
        if type(balance) is not int or not 0 <= balance <= 9_000_000_000_000_000:
            raise RunwayError('لم يرجع Runway رصيدًا صالحًا. لم يُعتمد الاتصال.')
        return balance
    except RunwayError:
        raise
    except (httpx.HTTPError, ValueError):
        raise RunwayError('لم تصل نتيجة مؤكدة من Runway. أعد فحص الاتصال لاحقًا.') from None
