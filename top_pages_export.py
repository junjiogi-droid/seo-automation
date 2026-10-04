#!/usr/bin/env python3
"""
Top Pages Monetization Audit
Pulls the pages with the most clicks from the Search Console API, fetches each
page, and counts its affiliate links (A8.net / Amazon / Rakuten / etc.) and how
far down the page the first one appears.

Writes:
  - data/top_pages_{end_date}.csv   (uploaded as a workflow artifact)
  - "上位ページ収益導線" tab in the SEO自動分析 Google Sheet (cleared and rewritten
    on every run, created on first run if it doesn't exist yet)

Run manually:
    GOOGLE_CREDENTIALS="$(cat service-account.json)" python3 top_pages_export.py
"""

import csv
import json
import os
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
import logging

import requests
from google.oauth2.service_account import Credentials
from google.api_core.exceptions import GoogleAPIError
from googleapiclient.discovery import build
import gspread

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration (kept consistent with the other scripts)
DOMAIN = "junjiogiso.com"
SHEETS_ID = "1WR8YGvvnOpRBxEgwEGbjCTPkk8kbu67Le8Xg4vrKVXU"
SHEET_TITLE = "上位ページ収益導線"
SHEET_HEADER = [
    'タイムスタンプ', 'URL', 'タイトル', 'クリック数', '表示回数', 'CTR(%)', '平均掲載順位',
    'アフィリエイトリンク数', '最初のリンクの位置(%)', 'Rinker', '主なリンク先'
]

REPORT_LAG_DAYS = 3
WINDOW_DAYS = 28
TOP_N = 40
EXCLUDED_URL_PATTERN = '/category/'
USER_AGENT = 'Mozilla/5.0 (compatible; seo-automation/1.0; +https://junjiogiso.com)'

# Substrings of href that mark an outbound affiliate / shopping link.
AFFILIATE_PATTERNS = {
    'A8.net': ('px.a8.net', 'a8.net/svt', 'www.a8.net'),
    'Amazon': ('amazon.co.jp', 'amzn.to'),
    '楽天': ('rakuten.co.jp', 'a.r10.to', 'hb.afl.rakuten'),
    'もしも': ('af.moshimo.com', 'moshimo.com'),
    'バリューコマース': ('valuecommerce.com', 'ck.jp.ap.valuecommerce'),
    'Yahoo!ショッピング': ('shopping.yahoo.co.jp', 'ck.jp.ap.valuecommerce'),
    'afb': ('t.afi-b.com', 'afi-b.com'),
    'AccessTrade': ('h.accesstrade.net', 'accesstrade.net'),
}

SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]


def get_credentials():
    """Get Google credentials from environment variable or file (same pattern as the other scripts)."""
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            return Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        return Credentials.from_service_account_file('service-account.json', scopes=SCOPES)
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        raise


def fetch_top_pages(service, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Top pages by clicks over the window, excluding category pages."""
    try:
        pages: Dict[str, Dict[str, Any]] = {}
        start_row = 0
        page_size = 25000

        while True:
            response = service.searchanalytics().query(
                siteUrl=f'sc-domain:{DOMAIN}',
                body={
                    'startDate': start_date,
                    'endDate': end_date,
                    'dimensions': ['page'],
                    'rowLimit': page_size,
                    'startRow': start_row,
                }
            ).execute()

            rows = response.get('rows', [])
            if not rows:
                break

            for row in rows:
                url = row['keys'][0]
                if EXCLUDED_URL_PATTERN in url:
                    continue
                pages[url] = {
                    'url': url,
                    'clicks': row.get('clicks', 0),
                    'impressions': row.get('impressions', 0),
                    'ctr': row.get('ctr', 0.0),
                    'position': row.get('position', 0.0),
                }

            if len(rows) < page_size:
                break
            start_row += page_size

        ranked = sorted(pages.values(), key=lambda p: (p['clicks'], p['impressions']), reverse=True)
        return ranked[:TOP_N]
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching pages: {e}")
        raise


class ArticleLinkParser(HTMLParser):
    """Collects <title>, and outbound links inside <article> with their character offset."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self._in_title = False
        self._article_depth = 0
        self.text_len = 0
        self.links: List[Dict[str, Any]] = []
        self.has_rinker = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self._in_title = True
        elif tag == 'article':
            self._article_depth += 1
        elif self._article_depth:
            if tag == 'a' and attrs.get('href'):
                self.links.append({'href': attrs['href'], 'offset': self.text_len})
            cls = attrs.get('class') or ''
            if 'yyi-rinker' in cls:
                self.has_rinker = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag == 'article' and self._article_depth:
            self._article_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._article_depth:
            self.text_len += len(data.strip())


def classify_link(href: str) -> Optional[str]:
    for name, patterns in AFFILIATE_PATTERNS.items():
        if any(p in href for p in patterns):
            return name
    return None


def audit_page(url: str) -> Dict[str, Any]:
    """Fetch the page and summarize its affiliate links. Returns blanks on fetch failure."""
    result = {'title': '', 'affiliate_count': '', 'first_pos_pct': '', 'rinker': '', 'networks': ''}
    try:
        response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Could not fetch {url}: {e}")
        return result

    parser = ArticleLinkParser()
    parser.feed(response.text)

    affiliate_links = []
    for link in parser.links:
        network = classify_link(link['href'])
        if network:
            affiliate_links.append({**link, 'network': network})

    result['title'] = re.sub(r'\s*-\s*junjiogiso\.com\s*$', '', parser.title.strip())
    result['affiliate_count'] = len(affiliate_links)
    result['rinker'] = 'あり' if parser.has_rinker else 'なし'
    if affiliate_links and parser.text_len:
        result['first_pos_pct'] = round(affiliate_links[0]['offset'] / parser.text_len * 100)
    counts: Dict[str, int] = {}
    for link in affiliate_links:
        counts[link['network']] = counts.get(link['network'], 0) + 1
    result['networks'] = ', '.join(f"{n}×{c}" for n, c in sorted(counts.items(), key=lambda x: -x[1]))
    return result


def build_rows(pages: List[Dict[str, Any]]) -> List[List[Any]]:
    timestamp = datetime.now().isoformat()
    rows = []
    for page in pages:
        audit = audit_page(page['url'])
        rows.append([
            timestamp, page['url'], audit['title'],
            int(page['clicks']), int(page['impressions']),
            round(page['ctr'] * 100, 2), round(page['position'], 1),
            audit['affiliate_count'], audit['first_pos_pct'], audit['rinker'], audit['networks'],
        ])
    return rows


def write_csv(rows: List[List[Any]], end_date: str) -> str:
    os.makedirs('data', exist_ok=True)
    path = f'data/top_pages_{end_date}.csv'
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(SHEET_HEADER)
        writer.writerows(rows)
    logger.info(f"Wrote CSV to {path}")
    return path


def write_to_sheets(rows: List[List[Any]]) -> bool:
    try:
        spreadsheet = gspread.authorize(get_credentials()).open_by_key(SHEETS_ID)
        try:
            worksheet = spreadsheet.worksheet(SHEET_TITLE)
        except gspread.exceptions.WorksheetNotFound:
            logger.info(f"'{SHEET_TITLE}' タブが無いため新規作成します")
            worksheet = spreadsheet.add_worksheet(title=SHEET_TITLE, rows=200, cols=len(SHEET_HEADER))

        worksheet.clear()
        worksheet.append_rows([SHEET_HEADER] + rows, value_input_option='USER_ENTERED')
        logger.info(f"Wrote {len(rows)} rows to '{SHEET_TITLE}'")
        return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    try:
        logger.info("Starting top pages monetization audit...")

        end = datetime.now() - timedelta(days=REPORT_LAG_DAYS)
        end_date = end.strftime('%Y-%m-%d')
        start_date = (end - timedelta(days=WINDOW_DAYS - 1)).strftime('%Y-%m-%d')
        logger.info(f"Analyzing period: {start_date} to {end_date}")

        service = build('webmasters', 'v3', credentials=get_credentials())
        pages = fetch_top_pages(service, start_date, end_date)
        logger.info(f"Auditing top {len(pages)} pages...")

        rows = build_rows(pages)
        write_csv(rows, end_date)

        if write_to_sheets(rows):
            logger.info("Top pages audit completed successfully")
            return 0

        logger.error("Failed to write data to Google Sheets")
        return 1
    except Exception as e:
        logger.error(f"Top pages audit failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
