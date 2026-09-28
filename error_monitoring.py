#!/usr/bin/env python3
"""
Search Console Daily Monitoring Script

NOTE (2026-09-28 fix): this used to call service.urlcrawlerrorscounts() and
service.indexingissues() - both come from the old "Webmaster Tools API" and
no longer exist on the Search Console API (webmasters v3). The current
discovery document only exposes `searchanalytics`, `sitemaps` and `sites`;
calling the old methods raised an AttributeError and made every scheduled
run of this script fail (exit code 1). There is no direct API replacement
for crawl-error / indexing-issue counts - that data now only lives in the
Search Console UI's Coverage report.

Rather than leave the daily job broken, it now does something GSC's API can
actually answer: a day-over-day traffic-drop watcher. It compares each
page's clicks/impressions for the most recent complete day against that
page's trailing 7-day average and flags pages that fell off a cliff (e.g.
a page that suddenly stopped getting clicks/impressions - which is usually
a much stronger real-world signal than raw crawl-error counts anyway).
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

from google.oauth2.service_account import Credentials
from google.api_core.exceptions import GoogleAPIError
from googleapiclient.discovery import build
import gspread

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
DOMAIN = "junjiogiso.com"
SHEETS_ID = "1WR8YGvvnOpRBxEgwEGbjCTPkk8kbu67Le8Xg4vrKVXU"
ERROR_MONITORING_GID = 0

# GSC data has a ~2-3 day lag before it's complete.
REPORT_LAG_DAYS = 3
BASELINE_DAYS = 7  # trailing window used to establish "normal" for a page

# A metric needs at least this much baseline traffic (daily average over the
# baseline window) before a drop in that metric is worth flagging. Each metric
# is gated separately - otherwise pages averaging 0.1 clicks/day show up as
# "100% drop" whenever they get 0 on a single day, which is just noise.
MIN_BASELINE_CLICKS_PER_DAY = 1.0
MIN_BASELINE_IMPRESSIONS_PER_DAY = 10.0
DROP_THRESHOLD = 0.5  # flag if clicks or impressions fell 50%+ vs baseline daily avg

# Google Sheets Scopes
SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]


def get_credentials():
    """Get Google credentials from environment variable or file."""
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            return credentials
        else:
            # Fallback to service account file
            credentials = Credentials.from_service_account_file(
                'service-account.json', scopes=SCOPES
            )
            return credentials
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        raise


def get_search_console_client():
    """Create Search Console API client."""
    credentials = get_credentials()
    return build('webmasters', 'v3', credentials=credentials)


def get_gsheets_client():
    """Create Google Sheets client."""
    credentials = get_credentials()
    return gspread.authorize(credentials)


def fetch_page_performance(service, start_date: str, end_date: str) -> Dict[str, Dict[str, float]]:
    """Fetch per-page clicks/impressions for a date range (dimension = page)."""
    try:
        pages: Dict[str, Dict[str, float]] = {}
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
                page_url = row['keys'][0]
                pages[page_url] = {
                    'clicks': row.get('clicks', 0),
                    'impressions': row.get('impressions', 0),
                }

            if len(rows) < page_size:
                break
            start_row += page_size

        return pages
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching page performance: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching page performance: {e}")
        raise


def detect_drops(latest_day: Dict[str, Dict[str, float]],
                  baseline: Dict[str, Dict[str, float]],
                  baseline_days: int) -> List[Dict[str, Any]]:
    """Flag pages whose latest-day clicks/impressions fell sharply vs their trailing baseline average."""
    drops = []

    for page_url, base in baseline.items():
        base_clicks_avg = base['clicks'] / baseline_days
        base_impr_avg = base['impressions'] / baseline_days

        latest = latest_day.get(page_url, {'clicks': 0, 'impressions': 0})

        # Only judge a metric if the page had enough of it to begin with
        click_drop = 0
        if base_clicks_avg >= MIN_BASELINE_CLICKS_PER_DAY:
            click_drop = (base_clicks_avg - latest['clicks']) / base_clicks_avg

        impr_drop = 0
        if base_impr_avg >= MIN_BASELINE_IMPRESSIONS_PER_DAY:
            impr_drop = (base_impr_avg - latest['impressions']) / base_impr_avg

        if click_drop >= DROP_THRESHOLD or impr_drop >= DROP_THRESHOLD:
            drops.append({
                'page_url': page_url,
                'baseline_clicks_avg': round(base_clicks_avg, 1),
                'latest_clicks': int(latest['clicks']),
                'click_drop_pct': round(click_drop * 100, 1),
                'baseline_impressions_avg': round(base_impr_avg, 1),
                'latest_impressions': int(latest['impressions']),
                'impression_drop_pct': round(impr_drop * 100, 1),
            })

    drops.sort(key=lambda d: max(d['click_drop_pct'], d['impression_drop_pct']), reverse=True)
    return drops


def prepare_error_data(drops: List[Dict[str, Any]]) -> List[List[Any]]:
    """Prepare drop-alert data for Google Sheets (keeps the original 5-column shape)."""
    rows = []
    timestamp = datetime.now().isoformat()

    for d in drops:
        if d['click_drop_pct'] >= DROP_THRESHOLD * 100:
            note = f"クリック {d['baseline_clicks_avg']}/日 → {d['latest_clicks']}"
            rows.append([timestamp, 'クリック急落', d['page_url'], f"{d['click_drop_pct']}%減", note])
        if d['impression_drop_pct'] >= DROP_THRESHOLD * 100:
            note = f"表示回数 {d['baseline_impressions_avg']}/日 → {d['latest_impressions']}"
            rows.append([timestamp, '表示回数急落', d['page_url'], f"{d['impression_drop_pct']}%減", note])

    return rows


def write_to_sheets(data: List[List[Any]]) -> bool:
    """Write error data to Google Sheets."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet_by_id(ERROR_MONITORING_GID)

        if not worksheet:
            logger.error(f"Worksheet with GID {ERROR_MONITORING_GID} not found")
            return False

        if data:
            # Append data to the sheet
            worksheet.append_rows(data, value_input_option='USER_ENTERED')
            logger.info(f"Successfully wrote {len(data)} rows to Google Sheets")
            return True
        else:
            logger.info("No drops detected today - nothing to write")
            return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    """Main execution function."""
    try:
        logger.info("Starting daily traffic-drop monitoring...")

        latest_day_end = (datetime.now() - timedelta(days=REPORT_LAG_DAYS)).strftime('%Y-%m-%d')
        latest_day_start = latest_day_end

        baseline_end = (datetime.now() - timedelta(days=REPORT_LAG_DAYS + 1)).strftime('%Y-%m-%d')
        baseline_start = (datetime.now() - timedelta(days=REPORT_LAG_DAYS + BASELINE_DAYS)).strftime('%Y-%m-%d')

        sc_service = get_search_console_client()

        logger.info(f"Fetching latest-day page performance: {latest_day_start}")
        latest_day = fetch_page_performance(sc_service, latest_day_start, latest_day_end)

        logger.info(f"Fetching baseline page performance: {baseline_start}..{baseline_end}")
        baseline = fetch_page_performance(sc_service, baseline_start, baseline_end)

        logger.info(f"Latest day: {len(latest_day)} pages | Baseline: {len(baseline)} pages")

        drops = detect_drops(latest_day, baseline, BASELINE_DAYS)
        logger.info(f"Detected {len(drops)} pages with a significant drop")

        error_data = prepare_error_data(drops)

        if write_to_sheets(error_data):
            logger.info("Daily monitoring completed successfully")
            return 0
        else:
            logger.error("Failed to write data to Google Sheets")
            return 1

    except Exception as e:
        logger.error(f"Daily monitoring failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
