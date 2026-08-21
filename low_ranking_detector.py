#!/usr/bin/env python3
"""
Low Ranking Keyword Detector
Detects keywords that have experienced significant ranking drops
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any
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
LOW_RANKING_GID = 953824174

RANKING_DROP_THRESHOLD = 5  # Keywords that dropped 5+ positions
MIN_IMPRESSIONS = 10  # Minimum impressions to consider

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


def fetch_rankings(service, start_date: str, end_date: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetch keyword rankings from Search Console API.

    Args:
        service: Search Console API client
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dictionary of keywords with ranking data
    """
    try:
        keywords = {}

        request_body = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': ['query'],
            'rowLimit': 10000,  # Get top 10000 queries
            'dimensionFilterGroups': [
                {
                    'filters': [
                        {
                            'dimension': 'impressions',
                            'operator': 'GREATER_THAN',
                            'expression': str(MIN_IMPRESSIONS)
                        }
                    ]
                }
            ]
        }

        response = service.searchanalytics().query(
            siteUrl=f'sc-domain:{DOMAIN}',
            body=request_body
        ).execute()

        if 'rows' in response:
            for row in response['rows']:
                query = row['keys'][0]
                keywords[query] = {
                    'impressions': row.get('impressions', 0),
                    'clicks': row.get('clicks', 0),
                    'ctr': row.get('ctr', 0),
                    'position': row.get('position', 100)
                }

        return keywords
    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching rankings: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching rankings: {e}")
        raise


def detect_drops(current_rankings: Dict[str, Dict[str, Any]],
                 previous_rankings: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect keywords with significant ranking drops.

    Args:
        current_rankings: Current week's rankings
        previous_rankings: Previous week's rankings

    Returns:
        List of keywords with ranking drops
    """
    drops = []

    for query, current_data in current_rankings.items():
        if query in previous_rankings:
            previous_data = previous_rankings[query]
            current_pos = current_data['position']
            previous_pos = previous_data['position']

            # Calculate position change (positive = drop, negative = improvement)
            position_change = current_pos - previous_pos

            # If position dropped by threshold or more
            if position_change >= RANKING_DROP_THRESHOLD:
                drops.append({
                    'timestamp': datetime.now().isoformat(),
                    'query': query,
                    'previous_position': previous_pos,
                    'current_position': current_pos,
                    'position_change': position_change,
                    'impressions': current_data['impressions'],
                    'clicks': current_data['clicks'],
                    'ctr': current_data['ctr'],
                    'status': 'Detected'
                })

    # Sort by position change (largest drops first)
    drops.sort(key=lambda x: x['position_change'], reverse=True)

    return drops


def prepare_sheet_data(drops: List[Dict[str, Any]]) -> List[List[Any]]:
    """Prepare data for Google Sheets."""
    rows = []
    for drop in drops:
        rows.append([
            drop['timestamp'],
            drop['query'],
            drop['previous_position'],
            drop['current_position'],
            drop['position_change'],
            int(drop['impressions']),
            int(drop['clicks']),
            round(drop['ctr'] * 100, 2),
            drop['status']
        ])
    return rows


def clear_existing_data():
    """Clear existing data in the worksheet."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet(LOW_RANKING_GID)

        if worksheet:
            # Get all data and delete rows except header
            all_values = worksheet.get_all_values()
            if len(all_values) > 1:
                worksheet.delete_rows(2, len(all_values))
                logger.info(f"Cleared {len(all_values) - 1} existing rows")
        return True
    except Exception as e:
        logger.error(f"Error clearing existing data: {e}")
        return False


def write_to_sheets(data: List[List[Any]]) -> bool:
    """Write ranking drop data to Google Sheets."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet(LOW_RANKING_GID)

        if not worksheet:
            logger.error(f"Worksheet with GID {LOW_RANKING_GID} not found")
            return False

        if data:
            worksheet.append_rows(data, value_input_option='USER_ENTERED')
            logger.info(f"Successfully wrote {len(data)} ranking drops to Google Sheets")
            return True
        else:
            logger.info("No ranking drops detected")
            return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    """Main execution function."""
    try:
