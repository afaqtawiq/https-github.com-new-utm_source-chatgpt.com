"""Browser navigation recovery while preserving API authentication responses."""
import html
from urllib.parse import quote, urlsplit

from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse


def safe_next(value):
    value = str(value or "")
    if not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(c) < 32 for c in value):
        return "/dashboard"
    parsed = urlsplit(value)
    if parsed.netloc or parsed.scheme or parsed.path.startswith(("/login", "/logout")):
        return "/dashboard"
    return value


async def operational_http_error(request, exc):
    is_page = "text/html" in request.headers.get("accept", "") and not request.url.path.startswith(("/api/", "/webhooks/"))
    if is_page and exc.status_code == 401 and request.url.path != "/login":
        target = request.url.path if request.method in ("GET", "HEAD") else "/dashboard"
        return RedirectResponse("/login?next=" + quote(safe_next(target), safe=""), 303)
    if is_page and exc.status_code in (400, 403, 404, 409, 422, 428):
        detail = html.escape(str(exc.detail or "تعذر إتمام الطلب"))
        return HTMLResponse("<!doctype html><html lang=ar dir=rtl><meta charset=utf-8>"
                            "<meta name=viewport content='width=device-width,initial-scale=1'>"
                            "<title>مراجعة الطلب — آفاق طويق</title>"
                            "<body style='font-family:Arial;background:#07131f;color:#eef6fb;padding:32px'>"
                            "<h1>تعذر إتمام الإجراء</h1><p>" + detail + "</p>"
                            "<a style='color:#86efac' href='/dashboard'>العودة إلى لوحة التشغيل</a></body></html>", exc.status_code)
    return await http_exception_handler(request, exc)
