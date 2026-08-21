#!/usr/bin/env python3
"""
Search Console Error Monitoring Script
Monitors crawl errors, indexing issues, and other errors from Google Search Console
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

from google.auth.transport.requests import Request
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


def fetch_crawl_errors(service, start_date: str, end_date: str) -> Dict[str, int]:
    """
    Fetch crawl errors from Search Console API.

    Args:
        service: Search Console API client
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dictionary of error types and counts
    """
    try:
        error_types = {}

        # Query parameters
        request_body = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['errorType'],
            'rowLimit': 1000
        }

        response = service.searchanalytics().query(
            siteUrl=f'sc-domain:{DOMAIN}',
            body=request_body
        ).execute()

        if 'rows' in response:
            for row in response['rows']:
                error_type = row['keys'][0]
                clicks = row.get('clicks', 0)
                error_types[error_type] = error_types.get(error_type, 0) + int(clicks)

        return error_types
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching crawl errors: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching crawl errors: {e}")
        raise


def fetch_indexing_issues(service) -> Dict[str, Any]:
    """Fetch indexing issues from Search Console API."""
    try:
        request_body = {
            'startDate': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
            'endDate': datetime.now().strftime('%Y-%m-%d'),
            'dimensions': ['issueType'],
            'rowLimit': 1000
        }

        response = service.searchanalytics().query(
            siteUrl=f'sc-domain:{DOMAIN}',
            body=request_body
        ).execute()

        issues = {}
        if 'rows' in response:
            for row in response['rows']:
                issue_type = row['keys'][0]
                impressions = row.get('impressions', 0)
                issues[issue_type] = issues.get(issue_type, 0) + int(impressions)

        return issues
    except Exception as e:
        logger.error(f"Error fetching indexing issues: {e}")
        return {}


def prepare_error_data(crawl_errors: Dict[str, int], indexing_issues: Dict[str, int]) -> List[List[Any]]:
    """Prepare error data for Google Sheets."""
    rows = []
    timestamp = datetime.now().isoformat()

    # Add crawl errors
    for error_type, count in crawl_errors.items():
        rows.append([timestamp, 'Crawl Error', error_type, count, ''])

    # Add indexing issues
    for issue_type, count in indexing_issues.items():
        rows.append([timestamp, 'Indexing Issue', issue_type, count, ''])

    return rows


def write_to_sheets(data: List[List[Any]]) -> bool:
    """Write error data to Google Sheets."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet(ERROR_MONITORING_GID)

        if not worksheet:
            logger.error(f"Worksheet with GID {ERROR_MONITORING_GID} not found")
            return False

        if data:
            # Append data to the sheet
            worksheet.append_rows(data, value_input_option='USER_ENTERED')
            logger.info(f"Successfully wrote {len(data)} rows to Google Sheets")
            return True
        else:
            logger.info("No error data to write")
            return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    """Main execution function."""
    try:
        logger.info("Starting error monitoring...")

        # Calculate date range (last 7 days)
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        # Get Search Console client
        sc_service = get_search_console_client()

        # Fetch errors
        logger.info(f"Fetching errors from {start_date} to {end_date}")
        crawl_errors = fetch_crawl_errors(sc_service, start_date, end_date)
        indexing_issues = fetch_indexing_issues(sc_service)

        logger.info(f"Found {len(crawl_errors)} crawl error types")
        logger.info(f"Found {len(indexing_issues)} indexing issue types")

        # Prepare and write data
        error_data = prepare_error_data(crawl_errors, indexing_issues)

        if write_to_sheets(error_data):
            logger.info("Error monitoring completed successfully")
            return 0
        else:
            logger.error("Failed to write data to Google Sheets")
            return 1

    except Exception as e:
        logger.error(f"Error monitoring failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
