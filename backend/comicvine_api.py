"""
Comic Vine API integration for comic book information lookup.
Provides functions to search for comic volumes (series) and individual issues.
Uses the Comic Vine API (requires an API key).
"""

import logging
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ComicVineClient:
    """Client for interacting with the Comic Vine API."""

    BASE_URL = 'https://comicvine.gamespot.com/api'

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {'accept': 'application/json'}

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if params is None:
            params = {}

        params['api_key'] = self.api_key
        params['format'] = 'json'

        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if data.get('status_code') != 1:
                logger.error(f"Comic Vine API error: {data.get('error', 'Unknown error')}")
                return None

            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Comic Vine API request failed for {endpoint}: {e}")
            return None

    def search_volume(self, volume_name: str) -> Optional[Dict]:
        """
        Search for a comic volume/series by name.

        Returns:
            Dict with 'name', 'start_year', 'publisher', 'count_of_issues', 'id', 'deck' or None
        """
        logger.info(f"Searching Comic Vine for volume: {volume_name}")

        params = {
            'filter': f'name:{volume_name}',
            'limit': 1,
            'field_list': 'name,start_year,publisher,count_of_issues,id,deck,image'
        }

        data = self._make_request('/volumes/', params)

        if data and data.get('results'):
            result = data['results'][0]
            publisher_name = 'Unknown'
            if result.get('publisher'):
                if isinstance(result['publisher'], dict):
                    publisher_name = result['publisher'].get('name', 'Unknown')
                else:
                    publisher_name = str(result['publisher'])

            formatted = {
                'name': result.get('name', 'Unknown'),
                'start_year': str(result.get('start_year', 'Unknown')),
                'publisher': publisher_name,
                'count_of_issues': result.get('count_of_issues', 0),
                'id': result.get('id', ''),
                'deck': result.get('deck', '')
            }

            logger.info(f"Found volume: {formatted['name']} ({formatted['start_year']}) by {formatted['publisher']}")
            return formatted

        logger.warning(f"No volume found for: {volume_name}")
        return None

    def search_issue(self, issue_name: str) -> Optional[Dict]:
        """
        Search for a specific comic issue by name.

        Returns:
            Dict with 'name', 'issue_number', 'cover_date', 'volume', 'id', 'deck' or None
        """
        logger.info(f"Searching Comic Vine for issue: {issue_name}")

        params = {
            'filter': f'name:{issue_name}',
            'limit': 1,
            'field_list': 'name,issue_number,cover_date,volume,id,deck,image'
        }

        data = self._make_request('/issues/', params)

        if data and data.get('results'):
            result = data['results'][0]
            volume_name = 'Unknown'
            volume_year = 'Unknown'
            if result.get('volume'):
                if isinstance(result['volume'], dict):
                    volume_name = result['volume'].get('name', 'Unknown')
                    volume_year = str(result['volume'].get('start_year', 'Unknown'))
                else:
                    volume_name = str(result['volume'])

            formatted = {
                'name': result.get('name', 'Unknown'),
                'issue_number': result.get('issue_number', 'Unknown'),
                'cover_date': result.get('cover_date', 'Unknown'),
                'volume_name': volume_name,
                'volume_year': volume_year,
                'id': result.get('id', ''),
                'deck': result.get('deck', '')
            }

            logger.info(f"Found issue: {formatted['volume_name']} #{formatted['issue_number']} ({formatted['cover_date']})")
            return formatted

        logger.warning(f"No issue found for: {issue_name}")
        return None

    def get_issue_by_volume_and_number(self, volume_id: int, issue_number: str) -> Optional[Dict]:
        """
        Find a specific issue by volume ID and issue number.

        Args:
            volume_id: The Comic Vine volume ID
            issue_number: The issue number (e.g., '1', '25', '100')

        Returns:
            Dict with issue details or None
        """
        logger.info(f"Searching Comic Vine for volume {volume_id} issue #{issue_number}")

        params = {
            'filter': f'volume:{volume_id},issue_number:{issue_number}',
            'limit': 1,
            'field_list': 'name,issue_number,cover_date,volume,id,deck,image'
        }

        data = self._make_request('/issues/', params)

        if data and data.get('results'):
            result = data['results'][0]
            volume_name = 'Unknown'
            if result.get('volume') and isinstance(result['volume'], dict):
                volume_name = result['volume'].get('name', 'Unknown')

            formatted = {
                'name': result.get('name', 'Unknown'),
                'issue_number': result.get('issue_number', 'Unknown'),
                'cover_date': result.get('cover_date', 'Unknown'),
                'volume_name': volume_name,
                'id': result.get('id', ''),
                'deck': result.get('deck', '')
            }

            logger.info(f"Found issue: {formatted['volume_name']} #{formatted['issue_number']}")
            return formatted

        logger.warning(f"No issue found for volume {volume_id} #{issue_number}")
        return None


def format_comicvine_response(result: Optional[Dict], query_type: str = 'volume') -> str:
    """
    Format Comic Vine API result as a natural language response for AI tool use.

    Args:
        result: Result from Comic Vine search
        query_type: Type of query ('volume', 'issue', or 'issue_by_number')

    Returns:
        Formatted string response
    """
    if not result:
        return "No results found in Comic Vine."

    if query_type == 'volume':
        response = (f"Comic Volume/Series: {result['name']}\n"
                    f"Start Year: {result['start_year']}\n"
                    f"Publisher: {result['publisher']}\n"
                    f"Total Issues: {result.get('count_of_issues', 'N/A')}\n"
                    f"Comic Vine ID: {result.get('id', 'N/A')}")
        if result.get('deck'):
            response += f"\nDescription: {result['deck']}"
        return response

    elif query_type == 'issue':
        response = (f"Comic Issue: {result['name']}\n"
                    f"Volume/Series: {result['volume_name']}\n"
                    f"Issue Number: {result['issue_number']}\n"
                    f"Cover Date: {result['cover_date']}")
        if result.get('volume_year') and result['volume_year'] != 'Unknown':
            response += f"\nSeries Start Year: {result['volume_year']}"
        if result.get('deck'):
            response += f"\nDescription: {result['deck']}"
        return response

    elif query_type == 'issue_by_number':
        response = (f"Comic Issue: {result['name']}\n"
                    f"Volume/Series: {result['volume_name']}\n"
                    f"Issue Number: {result['issue_number']}\n"
                    f"Cover Date: {result['cover_date']}")
        if result.get('deck'):
            response += f"\nDescription: {result['deck']}"
        return response

    return str(result)