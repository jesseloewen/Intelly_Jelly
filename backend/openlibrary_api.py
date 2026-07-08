"""
Open Library API integration for book and audiobook information lookup.
Provides functions to search for books, authors, and retrieve chapter/edition details.
Uses the free Open Library API (no key required).
"""

import logging
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OpenLibraryClient:
    """Client for interacting with the Open Library API."""

    BASE_URL = 'https://openlibrary.org'

    def __init__(self):
        self.headers = {'accept': 'application/json'}

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if params is None:
            params = {}

        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Open Library API request failed for {endpoint}: {e}")
            return None

    def search_book(self, book_name: str) -> Optional[Dict]:
        """
        Search for a book by title and return basic information.

        Returns:
            Dict with 'title', 'author', 'year', 'key', 'edition_count' or None
        """
        logger.info(f"Searching Open Library for book: {book_name}")

        params = {
            'q': book_name,
            'limit': 1,
            'fields': 'key,title,author_name,first_publish_year,edition_count,cover_i,subject'
        }

        data = self._make_request('/search.json', params)

        if data and data.get('docs'):
            doc = data['docs'][0]

            result = {
                'title': doc.get('title', 'Unknown'),
                'author': doc.get('author_name', ['Unknown'])[0] if doc.get('author_name') else 'Unknown',
                'year': str(doc.get('first_publish_year', 'Unknown')),
                'key': doc.get('key', ''),
                'edition_count': doc.get('edition_count', 0),
                'subjects': doc.get('subject', [])[:5]
            }

            logger.info(f"Found book: {result['title']} by {result['author']} ({result['year']})")
            return result

        logger.warning(f"No book found for: {book_name}")
        return None

    def get_work_details(self, work_key: str) -> Optional[Dict]:
        """
        Get detailed information about a work including description and subjects.

        Returns:
            Dict with 'title', 'description', 'subjects', 'authors' or None
        """
        logger.info(f"Fetching work details for: {work_key}")

        data = self._make_request(f'{work_key}.json')

        if data:
            description = data.get('description', '')
            if isinstance(description, dict):
                description = description.get('value', '')

            result = {
                'title': data.get('title', 'Unknown'),
                'description': str(description)[:500] if description else '',
                'subjects': data.get('subjects', [])[:5],
                'first_publish_date': data.get('first_publish_date', ''),
                'key': data.get('key', '')
            }

            author_refs = data.get('authors', [])
            if author_refs:
                author_key = author_refs[0].get('author', {}).get('key', '')
                if author_key:
                    author_info = self._make_request(f'{author_key}.json')
                    if author_info:
                        result['author'] = author_info.get('name', 'Unknown')

            if 'author' not in result:
                result['author'] = 'Unknown'

            logger.info(f"Retrieved work details for: {result['title']}")
            return result

        logger.warning(f"No work details found for: {work_key}")
        return None

    def search_audiobook(self, book_name: str) -> Optional[Dict]:
        """
        Search for an audiobook by title — uses the same search but
        returns edition information suitable for audiobook organization.

        Returns:
            Dict with same fields as search_book plus narrators if available
        """
        logger.info(f"Searching Open Library for audiobook: {book_name}")

        params = {
            'q': book_name,
            'limit': 1,
            'fields': 'key,title,author_name,first_publish_year,edition_count,subject,language'
        }

        data = self._make_request('/search.json', params)

        if data and data.get('docs'):
            doc = data['docs'][0]

            result = {
                'title': doc.get('title', 'Unknown'),
                'author': doc.get('author_name', ['Unknown'])[0] if doc.get('author_name') else 'Unknown',
                'year': str(doc.get('first_publish_year', 'Unknown')),
                'key': doc.get('key', ''),
                'edition_count': doc.get('edition_count', 0),
                'language': doc.get('language', ['eng'])[0] if doc.get('language') else 'eng'
            }

            logger.info(f"Found audiobook: {result['title']} by {result['author']} ({result['year']})")
            return result

        logger.warning(f"No audiobook found for: {book_name}")
        return None

    def get_book_chapters(self, book_name: str) -> Optional[Dict]:
        """
        Search for a book and try to retrieve chapter/toc information.
        Open Library doesn't have a direct chapter API, so we search for
        the book and return structured metadata useful for naming.

        Returns:
            Dict with 'title', 'author', 'year', 'subjects', 'description' or None
        """
        search_result = self.search_book(book_name)
        if not search_result:
            return None

        work_key = search_result.get('key', '')
        if not work_key:
            return search_result

        details = self.get_work_details(work_key)
        if details:
            return {
                'title': details.get('title', search_result['title']),
                'author': details.get('author', search_result['author']),
                'year': search_result['year'],
                'subjects': details.get('subjects', []),
                'description': details.get('description', ''),
                'first_publish_date': details.get('first_publish_date', '')
            }

        return search_result

    def search_author(self, author_name: str) -> Optional[Dict]:
        """
        Search for an author and return their information.

        Returns:
            Dict with 'name', 'key', 'birth_date', 'top_works' or None
        """
        logger.info(f"Searching Open Library for author: {author_name}")

        params = {
            'q': author_name,
            'limit': 1
        }

        data = self._make_request('/search/authors.json', params)

        if data and data.get('docs'):
            doc = data['docs'][0]

            result = {
                'name': doc.get('name', 'Unknown'),
                'key': doc.get('key', ''),
                'birth_date': doc.get('birth_date', ''),
                'top_work': doc.get('top_work', ''),
                'work_count': doc.get('work_count', 0)
            }

            logger.info(f"Found author: {result['name']}")
            return result

        logger.warning(f"No author found for: {author_name}")
        return None


def format_openlibrary_response(result: Optional[Dict], query_type: str = 'book') -> str:
    """
    Format Open Library API result as a natural language response for AI tool use.

    Args:
        result: Result from Open Library search
        query_type: Type of query ('book', 'audiobook', 'author', or 'chapters')

    Returns:
        Formatted string response
    """
    if not result:
        return "No results found in Open Library."

    if query_type == 'book':
        response = (f"Book: {result['title']}\n"
                    f"Author: {result['author']}\n"
                    f"First Published: {result['year']}\n"
                    f"Editions: {result.get('edition_count', 'N/A')}\n"
                    f"Open Library Key: {result.get('key', 'N/A')}")
        if result.get('subjects'):
            response += f"\nSubjects: {', '.join(result['subjects'][:5])}"
        return response

    elif query_type == 'audiobook':
        response = (f"Audiobook: {result['title']}\n"
                    f"Author: {result['author']}\n"
                    f"First Published: {result['year']}\n"
                    f"Language: {result.get('language', 'N/A')}")
        return response

    elif query_type == 'chapters':
        response = (f"Book: {result['title']}\n"
                    f"Author: {result['author']}\n"
                    f"Year: {result['year']}\n"
                    f"First Published: {result.get('first_publish_date', 'Unknown')}")
        if result.get('description'):
            desc = str(result['description'])[:300]
            response += f"\nDescription: {desc}..."
        if result.get('subjects'):
            response += f"\nSubjects: {', '.join(result['subjects'][:5])}"
        response += "\n(Note: Open Library does not provide chapter-level data. Use this metadata to infer standard book structure.)"
        return response

    elif query_type == 'author':
        response = (f"Author: {result['name']}\n"
                    f"Born: {result.get('birth_date', 'Unknown')}\n"
                    f"Notable Work: {result.get('top_work', 'N/A')}\n"
                    f"Total Works: {result.get('work_count', 'N/A')}")
        return response

    return str(result)