#!/usr/bin/env python3
"""
GA4 Weekly Export
Pulls site-wide traffic, channel / source breakdowns, top pages and outbound
link clicks (event "click", per page and per destination domain) from the
Google Analytics Data API (GA4) and writes them to the SEO自動分析 sheet.

Writes:
  - "GA週次" tab   (appended every run - weekly trend of site totals,
                     channels and traffic sources)
  - "GAページ別" tab (cleared and rewritten - top pages by views with their
                     outbound click counts)
  - "GA外部リンク" tab (cleared and rewritten - outbound clicks by page and
                     destination domain, last 28 days)
  - data/ga_pages_{end_date}.csv  (uploaded as a workflow artifact)

Requires the service account (the one in GOOGLE_CREDENTIALS) to be added as a
viewer on the GA4 property, and the "Google Analytics Data API" to be enabled
in its Google Cloud project.

Run manually:
    GOOGLE_CREDENTIALS="$(cat service-account.json)" python3 ga_weekly_export.py
"""

import csv
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import gspread

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration (kept consistent with the other scripts)
GA_PROPERTY_ID = "320356050"  # junjiogiso.com - GA4
SHEETS_ID = "1WR8YGvvnOpRBxEgwEGbjCTPkk8kbu67Le8Xg4vrKVXU"

WEEKLY_SHEET_TITLE = "GA週次"
WEEKLY_HEADER = ['タイムスタンプ', '期間', '区分', '対象', 'アクティブユーザー', 'セッション', 'ページビュー', '新規ユーザー', '平均エンゲージメント(秒)']
PAGES_SHEET_TITLE = "GAページ別"
PAGES_HEADER = ['タイムスタンプ', 'ページ', 'ページビュー', 'アクティブユーザー', '平均エンゲージメント(秒)', '外部リンククリック', '主なクリック先']
LINKS_SHEET_TITLE = "GA外部リンク"
LINKS_HEADER = ['タイムスタンプ', 'ページ', 'クリック先ドメイン', 'クリック数']

# GA4 data for the most recent day is usually still being processed.
REPORT_LAG_DAYS = 1
SHORT_WINDOW_DAYS = 7
LONG_WINDOW_DAYS = 28
TOP_PAGES = 40
TOP_LINK_ROWS = 100

SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]


def get_credentials():
    """Get Google credentials from environment variable or file (same pattern as the other scripts)."""
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            info = json.loads(creds_json)
            # Log which service account / project is in use (neither is a secret) so that
            # permission problems can be matched against the GA4 and Cloud settings.
            logger.info(f"Service account: {info.get('client_email')} (project_id: {info.get('project_id')})")
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        return Credentials.from_service_account_file('service-account.json', scopes=SCOPES)
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        raise


def run_report(service, start: str, end: str, dimensions: List[str], metrics: List[str],
               dimension_filter: Optional[Dict[str, Any]] = None, limit: int = 10000,
               order_by_metric: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run one GA4 Data API report and return rows as {'dims': [...], 'metrics': [floats]}."""
    body: Dict[str, Any] = {
        'dateRanges': [{'startDate': start, 'endDate': end}],
        'dimensions': [{'name': d} for d in dimensions],
        'metrics': [{'name': m} for m in metrics],
        'limit': limit,
    }
    if dimension_filter:
        body['dimensionFilter'] = dimension_filter
    if order_by_metric:
        body['orderBys'] = [{'metric': {'metricName': order_by_metric}, 'desc': True}]

    try:
        response = service.properties().runReport(
            property=f'properties/{GA_PROPERTY_ID}', body=body
        ).execute()
    except HttpError as e:
        if e.resp.status in (401, 403):
            logger.error(
                "GA4 Data API access denied. Add the service account (client_email in "
                "GOOGLE_CREDENTIALS) as a viewer on the GA4 property and enable the "
                "'Google Analytics Data API' in its Google Cloud project."
            )
        raise

    rows = []
    for row in response.get('rows', []):
        rows.append({
            'dims': [d.get('value', '') for d in row.get('dimensionValues', [])],
            'metrics': [float(m.get('value', 0) or 0) for m in row.get('metricValues', [])],
        })
    return rows


def avg_engagement(duration: float, users: float) -> float:
    return round(duration / users, 1) if users else 0.0


def collect_weekly_rows(service, start: str, end: str, label: str, timestamp: str) -> List[List[Any]]:
    """Site total, per-channel and per-source/medium rows for one window."""
    rows: List[List[Any]] = []

    totals = run_report(
        service, start, end, [],
        ['activeUsers', 'sessions', 'screenPageViews', 'newUsers', 'userEngagementDuration'],
    )
    if totals:
        users, sessions, views, new_users, duration = totals[0]['metrics']
        rows.append([timestamp, label, 'サイト全体', '全体', int(users), int(sessions), int(views),
                     int(new_users), avg_engagement(duration, users)])

    channels = run_report(service, start, end, ['sessionDefaultChannelGroup'],
                          ['activeUsers', 'sessions'], order_by_metric='sessions')
    for row in channels:
        users, sessions = row['metrics']
        rows.append([timestamp, label, 'チャネル', row['dims'][0], int(users), int(sessions), '', '', ''])

    sources = run_report(service, start, end, ['sessionSourceMedium'],
                         ['activeUsers', 'sessions'], limit=15, order_by_metric='sessions')
    for row in sources:
        users, sessions = row['metrics']
        rows.append([timestamp, label, '参照元/メディア', row['dims'][0], int(users), int(sessions), '', '', ''])

    return rows


def collect_outbound_clicks(service, start: str, end: str) -> List[Dict[str, Any]]:
    """Outbound link clicks (GA4 enhanced-measurement event 'click') by page and destination domain."""
    click_filter = {
        'filter': {
            'fieldName': 'eventName',
            'stringFilter': {'matchType': 'EXACT', 'value': 'click'},
        }
    }
    rows = run_report(service, start, end, ['pagePath', 'linkDomain'], ['eventCount'],
                      dimension_filter=click_filter, order_by_metric='eventCount')
    return [{'page': r['dims'][0], 'domain': r['dims'][1] or '(不明)', 'clicks': int(r['metrics'][0])} for r in rows]


def collect_page_rows(service, start: str, end: str, clicks: List[Dict[str, Any]], timestamp: str) -> List[List[Any]]:
    pages = run_report(service, start, end, ['pagePath'],
                       ['screenPageViews', 'activeUsers', 'userEngagementDuration'],
                       limit=TOP_PAGES, order_by_metric='screenPageViews')

    clicks_by_page: Dict[str, Dict[str, int]] = {}
    for c in clicks:
        clicks_by_page.setdefault(c['page'], {})
        clicks_by_page[c['page']][c['domain']] = clicks_by_page[c['page']].get(c['domain'], 0) + c['clicks']

    rows = []
    for row in pages:
        path = row['dims'][0]
        views, users, duration = row['metrics']
        page_clicks = clicks_by_page.get(path, {})
        top_domains = ', '.join(
            f"{d}×{n}" for d, n in sorted(page_clicks.items(), key=lambda x: -x[1])[:3]
        )
        rows.append([timestamp, path, int(views), int(users), avg_engagement(duration, users),
                     sum(page_clicks.values()), top_domains])
    return rows


def get_or_create_worksheet(spreadsheet, title: str, header: List[str]):
    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"'{title}' タブが無いため新規作成します")
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(header))
        ws.append_row(header, value_input_option='USER_ENTERED')
        return ws


def write_csv(rows: List[List[Any]], end_date: str) -> str:
    os.makedirs('data', exist_ok=True)
    path = f'data/ga_pages_{end_date}.csv'
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(PAGES_HEADER)
        writer.writerows(rows)
    logger.info(f"Wrote CSV to {path}")
    return path


def write_to_sheets(weekly_rows, page_rows, link_rows) -> bool:
    try:
        spreadsheet = gspread.authorize(get_credentials()).open_by_key(SHEETS_ID)

        weekly_ws = get_or_create_worksheet(spreadsheet, WEEKLY_SHEET_TITLE, WEEKLY_HEADER)
        weekly_ws.append_rows(weekly_rows, value_input_option='USER_ENTERED')
        logger.info(f"Wrote {len(weekly_rows)} rows to '{WEEKLY_SHEET_TITLE}'")

        for title, header, rows in (
            (PAGES_SHEET_TITLE, PAGES_HEADER, page_rows),
            (LINKS_SHEET_TITLE, LINKS_HEADER, link_rows),
        ):
            ws = get_or_create_worksheet(spreadsheet, title, header)
            ws.clear()
            ws.append_rows([header] + rows, value_input_option='USER_ENTERED')
            logger.info(f"Wrote {len(rows)} rows to '{title}'")
        return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    try:
        logger.info("Starting GA4 weekly export...")

        end = datetime.now() - timedelta(days=REPORT_LAG_DAYS)
        end_date = end.strftime('%Y-%m-%d')
        short_start = (end - timedelta(days=SHORT_WINDOW_DAYS - 1)).strftime('%Y-%m-%d')
        long_start = (end - timedelta(days=LONG_WINDOW_DAYS - 1)).strftime('%Y-%m-%d')
        logger.info(f"Window: {long_start} to {end_date}")

        service = build('analyticsdata', 'v1beta', credentials=get_credentials(), cache_discovery=False)
        timestamp = datetime.now().isoformat()

        weekly_rows = (
            collect_weekly_rows(service, short_start, end_date, f'直近{SHORT_WINDOW_DAYS}日', timestamp)
            + collect_weekly_rows(service, long_start, end_date, f'直近{LONG_WINDOW_DAYS}日', timestamp)
        )

        clicks = collect_outbound_clicks(service, long_start, end_date)
        page_rows = collect_page_rows(service, long_start, end_date, clicks, timestamp)
        link_rows = [[timestamp, c['page'], c['domain'], c['clicks']] for c in clicks[:TOP_LINK_ROWS]]

        write_csv(page_rows, end_date)

        if write_to_sheets(weekly_rows, page_rows, link_rows):
            logger.info("GA4 weekly export completed successfully")
            return 0

        logger.error("Failed to write data to Google Sheets")
        return 1
    except Exception as e:
        logger.error(f"GA4 weekly export failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
