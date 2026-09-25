"""Prospects: shared imports, constants, tables. Imported with * by the other prospects_* modules.
"""
import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import urllib.parse
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.storage import db, execute, get_session, log, one, rows, utcnow
from app.fine_permissions import has_permission
from app.marketing_content import EMAIL, PHONE, WEBSITE, SUBJECT, email_address, whatsapp_number, message_text, message_html
from app.mail_delivery import MailConnectionFailed, MailRecipientRejected, delivery_notice

RIYADH = ZoneInfo('Asia/Riyadh')
PLACES_SEARCH = 'https://places.googleapis.com/v1/places:searchText'
FIELD_MASK = ','.join('places.' + f for f in (
    'id', 'displayName', 'formattedAddress', 'primaryTypeDisplayName', 'types', 'googleMapsUri',
    'businessStatus', 'nationalPhoneNumber', 'internationalPhoneNumber', 'websiteUri', 'rating',
    'userRatingCount')) + ',nextPageToken'
REGIONS = {'sa': 'السعودية', 'ae': 'الإمارات', 'kw': 'الكويت', 'bh': 'البحرين', 'qa': 'قطر', 'om': 'عُمان'}
FOLLOW_UP_DAYS = 7
PACE_SECONDS = 20  # spacing between sends protects sender reputation
FOLLOW_UP_SUBJECT = 'متابعة: خدمات آفاق طويق في ميناء جدة'

TARGET_TERMS = (
    'استيراد', 'مستورد', 'تصدير', 'مصدر', 'تجارة', 'تجارية', 'التجارية', 'مصنع', 'مصانع', 'صناعات', 'صناعية',
    'جملة', 'موزع', 'توزيع', 'مواد غذائية', 'أغذية', 'اغذية', 'قطع غيار', 'مواد بناء', 'أدوية', 'ادوية', 'معدات',
    'آلات', 'الات', 'أجهزة', 'اجهزة', 'إلكترونيات', 'الكترونيات', 'أثاث', 'اثاث', 'منسوجات', 'أقمشة', 'بلاستيك',
    'كيماويات', 'حديد', 'ورق', 'تغليف', 'مستلزمات', 'توريد', 'مورد', 'تصنيع', 'منتجات', 'import', 'export', 'trading', 'factory', 'manufactur',
    'industr', 'wholesale', 'wholesaler', 'distribut', 'supplier', 'supply', 'foods', 'spare parts', 'equipment',
)
COMPETITOR_TERMS = (
    'تخليص', 'مخلص', 'مخلصين', 'شحن', 'نقل', 'لوجست', 'لوجيست', 'فريت', 'كارقو', 'كارجو', 'شحنات',
    'freight', 'logistic', 'shipping', 'cargo', 'customs broker', 'clearance', 'forwarding', 'courier',
    'moving_company', 'trucking', 'movers',
)
IRRELEVANT_TERMS = (
    'مطعم', 'مقهى', 'كافيه', 'كوفي', 'صالون', 'مسجد', 'مدرسة', 'مستشفى', 'عيادة', 'فندق', 'صيدلية', 'بنك',
    'مغسلة', 'محطة وقود', 'نادي', 'حلاق', 'restaurant', 'cafe', 'coffee', 'beauty_salon', 'hair_care', 'mosque',
    'school', 'hospital', 'doctor', 'dentist', 'hotel', 'lodging', 'pharmacy', 'bank', 'atm', 'car_wash',
    'gas_station', 'gym', 'place_of_worship', 'meal_takeaway', 'bakery',
)
FREE_MAIL = {'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com', 'live.com', 'icloud.com', 'outlook.sa', 'hotmail.sa'}
JUNK_EMAIL = re.compile(r'(example|domain|yourdomain|email|sentry|wixpress|wix\.com|godaddy|sample|test)\.', re.I)
CONTACT_LINK = re.compile(r'href=["\']([^"\'#]+)["\'][^>]*>[^<]{0,80}(?:contact|اتصل|تواصل|اتصال)', re.I)
CONTACT_HREF = re.compile(r'href=["\']([^"\'#]*(?:contact|%d8%a7%d8%aa%d8%b5%d9%84|تواصل|اتصل)[^"\'#]*)["\']', re.I)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}')


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS prospects(
            id BIGSERIAL PRIMARY KEY, place_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT,
            types TEXT, address TEXT, region TEXT, phone TEXT, website TEXT, email TEXT, email_source TEXT,
            email_mx BOOLEAN, maps_url TEXT, business_status TEXT, rating DOUBLE PRECISION, rating_count INTEGER,
            score INTEGER NOT NULL DEFAULT 0, tier TEXT NOT NULL DEFAULT 'review', reasons TEXT,
            search_query TEXT, status TEXT NOT NULL DEFAULT 'new', unsubscribe_token TEXT UNIQUE NOT NULL,
            opportunity_id BIGINT, last_error TEXT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS prospects_email_uq ON prospects(lower(email)) WHERE email IS NOT NULL')
        c.execute('CREATE INDEX IF NOT EXISTS prospects_phone_idx ON prospects(phone)')
        c.execute('''CREATE TABLE IF NOT EXISTS prospect_messages(
            id BIGSERIAL PRIMARY KEY, prospect_id BIGINT NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
            step INTEGER NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL,
            provider_message_id TEXT, last_error TEXT, created_at TIMESTAMPTZ NOT NULL, sent_at TIMESTAMPTZ,
            UNIQUE(prospect_id, step))''')
        c.execute('''CREATE TABLE IF NOT EXISTS prospect_outreach(
            id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT FALSE, approved_by BIGINT,
            approved_at TIMESTAMPTZ, daily_cap INTEGER NOT NULL DEFAULT 20, last_error TEXT, last_run_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS marketing_suppressions(
            channel TEXT NOT NULL, recipient TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(channel,recipient))''')


init()
