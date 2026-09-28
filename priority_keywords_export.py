#!/usr/bin/env python3
"""
Priority Keyword CSV/Sheets Export
Pulls clicks / impressions / CTR / average position for the site as a whole
and for a fixed set of priority keywords directly from the Search Console
API (searchanalytics.query) - no manual "CSV export" from the GSC UI needed.

Writes:
  - data/priority_keywords_{end_date}.csv   (kept in the repo / uploaded as
    a workflow artifact so it can be downloaded straight from the Actions run)
  - "優先KW週次" tab in the existing SEO自動分析 Google Sheet (created on
    first run if it doesn't exist yet)

Run manually:
    GOOGLE_CREDENTIALS="$(cat service-account.json)" python3 priority_keywords_export.py
"""

import csv
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List
import logging

from google.oauth2.service_account import Credentials
from google.api_core.exceptions import GoogleAPIError
from googleapiclient.discovery import build
import gspread

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration (kept consistent with low_ranking_detector.py / rewrite_candidates.py)
DOMAIN = "junjiogiso.com"
SHEETS_ID = "1WR8YGvvnOpRBxEgwEGbjCTPkk8kbu67Le8Xg4vrKVXU"
PRIORITY_SHEET_TITLE = "優先KW週次"
PRIORITY_SHEET_HEADER = [
    'タイムスタンプ', '期間', '対象', 'クリック数', '表示回数', 'CTR(%)', '平均掲載順位'
]

# GSC data usually isn't complete for the last ~2-3 days yet, so end the
# window a few days back to avoid an artificially low/partial CTR.
REPORT_LAG_DAYS = 3
SHORT_WINDOW_DAYS = 7
LONG_WINDOW_DAYS = 28

# The keyword cluster we're actively tracking for the CTR improvement project.
# Edit this list as priorities change - everything else in the pipeline adapts.
PRIORITY_KEYWORDS = [
    "ドライヤー 何ワット",
    "ドライヤー何ワット",
    "ドライヤー ワット数",
    "ドライヤーワット数",
    "色落ちしにくいシャンプー",
]

SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]


def get_credentials():
    """Get Google credentials from environment variable or file (same pattern as the other scripts)."""
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return Credentials.from_service_account_file('service-account.json', scopes=SCOPES)
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        raise


def get_search_console_client():
    return build('webmasters', 'v3', credentials=get_credentials())


def get_gsheets_client():
    return gspread.authorize(get_credentials())


def fetch_site_totals(service, start_date: str, end_date: str) -> Dict[str, Any]:
    """Site-wide clicks/impressions/CTR/position for the window (no dimensions)."""
    try:
        response = service.searchanalytics().query(
            siteUrl=f'sc-domain:{DOMAIN}',
            body={'startDate': start_date, 'endDate': end_date}
        ).execute()
        rows = response.get('rows', [])
        if not rows:
            return {'clicks': 0, 'impressions': 0, 'ctr': 0.0, 'position': 0.0}
        row = rows[0]
        return {
            'clicks': row.get('clicks', 0),
            'impressions': row.get('impressions', 0),
            'ctr': row.get('ctr', 0.0),
            'position': row.get('position', 0.0),
        }
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching site totals: {e}")
        raise


def fetch_keyword_data(service, start_date: str, end_date: str, keywords: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch per-query metrics, then keep only rows matching our priority keyword
    list. Search Console can't filter by an arbitrary keyword *set* in one
    call, so we pull the query-dimension table (like the other scripts do)
    and filter client-side.
    """
    try:
        matched: Dict[str, Dict[str, Any]] = {}
        start_row = 0
        page_size = 25000

        while True:
            response = service.searchanalytics().query(
                siteUrl=f'sc-domain:{DOMAIN}',
                body={
                    'startDate': start_date,
                    'endDate': end_date,
                    'dimensions': ['query'],
                    'rowLimit': page_size,
                    'startRow': start_row,
                }
            ).execute()

            rows = response.get('rows', [])
            if not rows:
                break

            for row in rows:
                query = row['keys'][0]
                if query in keywords:
                    matched[query] = {
                        'clicks': row.get('clicks', 0),
                        'impressions': row.get('impressions', 0),
                        'ctr': row.get('ctr', 0.0),
                        'position': row.get('position', 0.0),
                    }

            if len(rows) < page_size:
                break
            start_row += page_size

        # Keywords with zero impressions in the window won't appear in the
        # API response at all - fill them in explicitly so the report still
        # shows "0" instead of silently omitting the row.
        for kw in keywords:
            matched.setdefault(kw, {'clicks': 0, 'impressions': 0, 'ctr': 0.0, 'position': 0.0})

        return matched
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching keyword data: {e}")
        raise


def build_report_rows(end_date: str, site_short, site_long, kw_short, kw_long) -> List[Dict[str, Any]]:
    timestamp = datetime.now().isoformat()
    rows = []

    rows.append({'timestamp': timestamp, 'period': f'直近{SHORT_WINDOW_DAYS}日', 'label': 'サイト全体', **site_short})
    rows.append({'timestamp': timestamp, 'period': f'直近{LONG_WINDOW_DAYS}日', 'label': 'サイト全体', **site_long})

    for kw in PRIORITY_KEYWORDS:
        rows.append({'timestamp': timestamp, 'period': f'直近{SHORT_WINDOW_DAYS}日', 'label': kw, **kw_short[kw]})
        rows.append({'timestamp': timestamp, 'period': f'直近{LONG_WINDOW_DAYS}日', 'label': kw, **kw_long[kw]})

    return rows


def write_csv(rows: List[Dict[str, Any]], end_date: str) -> str:
    os.makedirs('data', exist_ok=True)
    path = f'data/priority_keywords_{end_date}.csv'
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['タイムスタンプ', '期間', '対象', 'クリック数', '表示回数', 'CTR(%)', '平均掲載順位'])
        for r in rows:
            writer.writerow([
                r['timestamp'], r['period'], r['label'],
                int(r['clicks']), int(r['impressions']),
                round(r['ctr'] * 100, 2), round(r['position'], 1),
            ])
    logger.info(f"Wrote CSV to {path}")
    return path


def get_or_create_worksheet(spreadsheet):
    try:
        return spreadsheet.worksheet(PRIORITY_SHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"'{PRIORITY_SHEET_TITLE}' タブが無いため新規作成します")
        ws = spreadsheet.add_worksheet(title=PRIORITY_SHEET_TITLE, rows=1000, cols=len(PRIORITY_SHEET_HEADER))
        ws.append_row(PRIORITY_SHEET_HEADER, value_input_option='USER_ENTERED')
        return ws


def write_to_sheets(rows: List[Dict[str, Any]]) -> bool:
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = get_or_create_worksheet(spreadsheet)

        sheet_rows = [[
            r['timestamp'], r['period'], r['label'],
            int(r['clicks']), int(r['impressions']),
            round(r['ctr'] * 100, 2), round(r['position'], 1),
        ] for r in rows]

        worksheet.append_rows(sheet_rows, value_input_option='USER_ENTERED')
        logger.info(f"Wrote {len(sheet_rows)} rows to '{PRIORITY_SHEET_TITLE}'")
        return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    try:
        logger.info("Starting priority keyword export...")

        today = datetime.now()
        end = today - timedelta(days=REPORT_LAG_DAYS)
        end_date = end.strftime('%Y-%m-%d')
        short_start = (end - timedelta(days=SHORT_WINDOW_DAYS - 1)).strftime('%Y-%m-%d')
        long_start = (end - timedelta(days=LONG_WINDOW_DAYS - 1)).strftime('%Y-%m-%d')

        service = get_search_console_client()

        logger.info(f"Fetching site totals: {short_start}..{end_date} / {long_start}..{end_date}")
        site_short = fetch_site_totals(service, short_start, end_date)
        site_long = fetch_site_totals(service, long_start, end_date)

        logger.info("Fetching priority keyword data...")
        kw_short = fetch_keyword_data(service, short_start, end_date, PRIORITY_KEYWORDS)
        kw_long = fetch_keyword_data(service, long_start, end_date, PRIORITY_KEYWORDS)

        rows = build_report_rows(end_date, site_short, site_long, kw_short, kw_long)

        csv_path = write_csv(rows, end_date)
        sheets_ok = write_to_sheets(rows)

        logger.info(f"CSV: {csv_path} | Sheets write: {'OK' if sheets_ok else 'FAILED'}")
        return 0 if sheets_ok else 1

    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
