#!/usr/bin/env python3
"""
Rewrite Candidates Generator
Identifies pages that need rewriting based on ranking and CTR performance
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
REWRITE_CANDIDATES_GID = 1901160298

# Thresholds for rewrite candidates
MAX_RANKING_POSITION = 30  # Keywords ranked below 30
MIN_IMPRESSIONS = 10  # Minimum impressions to consider
LOW_CTR_THRESHOLD = 1.0  # CTR below 1%

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


def fetch_all_queries(service, start_date: str, end_date: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetch all queries from Search Console API.

    Args:
        service: Search Console API client
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dictionary of queries with performance data
    """
    try:
        queries = {}
        start_index = 0
        page_size = 10000

        while True:
            request_body = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': ['query', 'page'],
                'rowLimit': page_size,
                'startRow': start_index,
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

            if 'rows' not in response or len(response['rows']) == 0:
                break

            for row in response['rows']:
                query = row['keys'][0]
                page_url = row['keys'][1]
                position = row.get('position', 100)

                if position >= MAX_RANKING_POSITION:  # Only interested in low-ranking keywords
                    key = f"{query}|{page_url}"
                    queries[key] = {
                        'query': query,
                        'page_url': page_url,
                        'position': position,
                        'impressions': row.get('impressions', 0),
                        'clicks': row.get('clicks', 0),
                        'ctr': row.get('ctr', 0)
                    }

            start_index += page_size
            logger.info(f"Fetched {len(queries)} candidates so far...")

            if len(response.get('rows', [])) < page_size:
                break

        return queries

    except GoogleAPIError as e:
        logger.error(f"Google API error while fetching queries: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching queries: {e}")
        raise


def prioritize_candidates(queries: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prioritize rewrite candidates based on potential impact.

    Criteria:
    1. Low CTR with decent impressions
    2. Position between 11-30 (easy to improve)
    3. High impression count (potential traffic)

    Args:
        queries: Dictionary of query data

    Returns:
        Sorted list of prioritized candidates
    """
    candidates = []

    for key, data in queries.items():
        # Calculate priority score
        # Higher impressions = higher priority (more traffic potential)
        # Lower CTR = higher priority (room for improvement)
        # Position 11-30 is better than 31+ (easier to rank)

        ctr = data['ctr'] * 100  # Convert to percentage
        impressions = data['impressions']
        position = data['position']

        # Priority formula
        # Lower position (closer to 10) = higher score
        # Higher impressions = higher score
        # Lower CTR = higher score
        position_score = max(0, 30 - position) / 20  # 0-1 scale
        impression_score = min(impressions / 100, 1.0)  # 0-1 scale (cap at 100 impressions)
        ctr_score = 1.0 - min(ctr / 5, 1.0)  # 0-1 scale (cap at 5% CTR)

        priority_score = (position_score * 0.3) + (impression_score * 0.4) + (ctr_score * 0.3)

        candidates.append({
            'timestamp': datetime.now().isoformat(),
            'query': data['query'],
            'page_url': data['page_url'],
            'current_position': position,
            'impressions': impressions,
            'clicks': int(data['clicks']),
            'ctr': ctr,
            'priority_score': priority_score,
            'priority_level': classify_priority(priority_score),
            'reason': generate_reason(ctr, position, impressions),
            'status': 'Pending'
        })

    # Sort by priority score (highest first)
    candidates.sort(key=lambda x: x['priority_score'], reverse=True)

    return candidates[:100]  # Return top 100 candidates


def classify_priority(score: float) -> str:
    """Classify priority level based on score."""
    if score >= 0.7:
        return 'High'
    elif score >= 0.4:
        return 'Medium'
    else:
        return 'Low'


def generate_reason(ctr: float, position: int, impressions: int) -> str:
    """Generate reason for rewrite recommendation."""
    reasons = []

    if ctr < LOW_CTR_THRESHOLD:
        reasons.append('Low CTR')

    if 11 <= position <= 20:
        reasons.append('Position 11-20')
    elif 21 <= position <= 30:
        reasons.append('Position 21-30')

    if impressions > 50:
        reasons.append('High impressions')

    return ' + '.join(reasons) if reasons else 'Needs optimization'


def prepare_sheet_data(candidates: List[Dict[str, Any]]) -> List[List[Any]]:
    """Prepare data for Google Sheets."""
    rows = []
    for candidate in candidates:
        rows.append([
            candidate['timestamp'],
            candidate['query'],
            candidate['page_url'],
            int(candidate['current_position']),
            int(candidate['impressions']),
            candidate['clicks'],
            round(candidate['ctr'], 2),
            candidate['priority_level'],
            round(candidate['priority_score'], 3),
            candidate['reason'],
            candidate['status']
        ])
    return rows


def clear_existing_data():
    """Clear existing data in the worksheet."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet(REWRITE_CANDIDATES_GID)

        if worksheet:
            all_values = worksheet.get_all_values()
            if len(all_values) > 1:
                worksheet.delete_rows(2, len(all_values))
                logger.info(f"Cleared {len(all_values) - 1} existing rows")
        return True
    except Exception as e:
        logger.error(f"Error clearing existing data: {e}")
        return False


def write_to_sheets(data: List[List[Any]]) -> bool:
    """Write rewrite candidate data to Google Sheets."""
    try:
        client = get_gsheets_client()
        spreadsheet = client.open_by_key(SHEETS_ID)
        worksheet = spreadsheet.get_worksheet(REWRITE_CANDIDATES_GID)

        if not worksheet:
            logger.error(f"Worksheet with GID {REWRITE_CANDIDATES_GID} not found")
            return False

        if data:
            # Split into chunks to avoid API limits
            chunk_size = 1000
            for i in range(0, len(data), chunk_size):
                chunk = data[i:i+chunk_size]
                worksheet.append_rows(chunk, value_input_option='USER_ENTERED')
                logger.info(f"Wrote {len(chunk)} candidates to Google Sheets")
            return True
        else:
            logger.info("No rewrite candidates found")
            return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def main():
    """Main execution function."""
    try:
        logger.info("Starting rewrite candidates generation...")

        # Calculate date range (last 30 days)
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        logger.info(f"Analyzing period: {start_date} to {end_date}")

        # Get Search Console client
        sc_service = get_search_console_client()

        # Fetch all queries
        logger.info("Fetching all queries from Search Console...")
        all_queries = fetch_all_queries(sc_service, start_date, end_date)
        logger.info(f"Found {len(all_queries)} potential candidates (position > 30)")

        # Prioritize candidates
        logger.info("Prioritizing candidates...")
        candidates = prioritize_candidates(all_queries)
        logger.info(f"Generated {len(candidates)} prioritized rewrite candidates")

        # Clear and write data
        if clear_existing_data():
            sheet_data = prepare_sheet_data(candidates)
            if write_to_sheets(sheet_data):
                logger.info("Rewrite candidates generation completed successfully")
                return 0

        logger.error("Failed to write data to Google Sheets")
        return 1

    except Exception as e:
        logger.error(f"Rewrite candidates generation failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
