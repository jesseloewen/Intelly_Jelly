"""
MusicBrainz API integration for music metadata lookup.
Provides functions to search for artists, releases, recordings, and release groups.
Uses the free MusicBrainz API (no key required).
"""

import logging
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MusicBrainzClient:
    """Client for interacting with the MusicBrainz API."""

    BASE_URL = 'https://musicbrainz.org/ws/2'

    def __init__(self):
        self.headers = {
            'User-Agent': 'IntellyJelly/1.0 ( music-organizer )',
            'accept': 'application/json'
        }

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if params is None:
            params = {}

        params['fmt'] = 'json'
        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"MusicBrainz API request failed for {endpoint}: {e}")
            return None

    def search_artist(self, artist_name: str) -> Optional[Dict]:
        """
        Search for an artist by name.

        Returns:
            Dict with 'name', 'id', 'type', 'country', 'disambiguation', 'tags', 'life_span' or None
        """
        logger.info(f"Searching MusicBrainz for artist: {artist_name}")

        params = {
            'query': f'artist:"{artist_name}"',
            'limit': 3
        }

        data = self._make_request('/artist/', params)

        if data and data.get('artists'):
            artist = data['artists'][0]

            life_span = artist.get('life-span', {})
            begin = life_span.get('begin', '')
            end = life_span.get('end', '')

            result = {
                'name': artist.get('name', 'Unknown'),
                'id': artist.get('id', ''),
                'type': artist.get('type', 'Unknown'),
                'country': artist.get('country', 'Unknown'),
                'disambiguation': artist.get('disambiguation', ''),
                'tags': [t.get('name', '') for t in artist.get('tags', [])[:5]],
                'life_span': f"{begin} - {end}" if end else begin if begin else 'Unknown',
                'total_results': len(data.get('artists', []))
            }

            logger.info(f"Found artist: {result['name']} ({result['type']})")
            return result

        logger.warning(f"No artist found for: {artist_name}")
        return None

    def search_release(self, release_name: str, artist_name: Optional[str] = None) -> Optional[Dict]:
        """
        Search for a music release (album, single, EP) by name and optionally artist.

        Returns:
            Dict with 'title', 'id', 'artist', 'date', 'country', 'status', 'tracks' or None
        """
        query = f'release:"{release_name}"'
        if artist_name:
            query += f' AND artist:"{artist_name}"'

        logger.info(f"Searching MusicBrainz for release: {release_name}" + (f" by {artist_name}" if artist_name else ""))

        params = {
            'query': query,
            'limit': 3
        }

        data = self._make_request('/release/', params)

        if data and data.get('releases'):
            release = data['releases'][0]

            artist_credit = release.get('artist-credit', [])
            artist_name_str = ''.join(
                ac.get('name', '') + (ac.get('joinphrase', '') if 'joinphrase' in ac else '')
                for ac in artist_credit
            )

            media = release.get('media', [])
            track_count = sum(m.get('track-count', 0) for m in media) if media else 0

            result = {
                'title': release.get('title', 'Unknown'),
                'id': release.get('id', ''),
                'artist': artist_name_str or 'Unknown',
                'date': release.get('date', 'Unknown'),
                'country': release.get('country', 'Unknown'),
                'status': release.get('status', 'Unknown'),
                'track_count': track_count,
                'total_results': len(data.get('releases', []))
            }

            logger.info(f"Found release: {result['title']} by {result['artist']} ({result['date']})")
            return result

        logger.warning(f"No release found for: {release_name}")
        return None

    def search_release_group(self, release_name: str, artist_name: Optional[str] = None) -> Optional[Dict]:
        """
        Search for a release group (album concept across all editions) by name.

        A release group represents the "album" concept, grouping together
        all different editions/releases (original, deluxe, remaster, etc.).

        Returns:
            Dict with 'title', 'id', 'artist', 'first_release_date', 'type', 'tags' or None
        """
        query = f'releasegroup:"{release_name}"'
        if artist_name:
            query += f' AND artist:"{artist_name}"'

        logger.info(f"Searching MusicBrainz for release group: {release_name}" + (f" by {artist_name}" if artist_name else ""))

        params = {
            'query': query,
            'limit': 3
        }

        data = self._make_request('/release-group/', params)

        if data and data.get('release-groups'):
            rg = data['release-groups'][0]

            artist_credit = rg.get('artist-credit', [])
            artist_name_str = ''.join(
                ac.get('name', '') + (ac.get('joinphrase', '') if 'joinphrase' in ac else '')
                for ac in artist_credit
            )

            result = {
                'title': rg.get('title', 'Unknown'),
                'id': rg.get('id', ''),
                'artist': artist_name_str or 'Unknown',
                'first_release_date': rg.get('first-release-date', 'Unknown'),
                'type': rg.get('primary-type', 'Unknown'),
                'secondary_types': rg.get('secondary-types', []),
                'tags': [t.get('name', '') for t in rg.get('tags', [])[:5]],
                'total_results': len(data.get('release-groups', []))
            }

            logger.info(f"Found release group: {result['title']} by {result['artist']} ({result['first_release_date']})")
            return result

        logger.warning(f"No release group found for: {release_name}")
        return None

    def get_release_tracks(self, release_id: str) -> Optional[Dict]:
        """
        Get detailed track listing for a release.

        Returns:
            Dict with 'title', 'artist', 'date', 'tracks' (list of track info) or None
        """
        logger.info(f"Fetching tracks for release: {release_id}")

        params = {
            'inc': 'recordings+artist-credits'
        }

        data = self._make_request(f'/release/{release_id}', params)

        if data:
            artist_credit = data.get('artist-credit', [])
            artist_name_str = ''.join(
                ac.get('name', '') + (ac.get('joinphrase', '') if 'joinphrase' in ac else '')
                for ac in artist_credit
            )

            tracks = []
            for m in data.get('media', []):
                disc_number = m.get('position', 1)
                for t in m.get('tracks', []):
                    track_artist_credit = t.get('artist-credit')
                    if track_artist_credit and track_artist_credit != artist_credit:
                        ta = ''.join(
                            ac.get('name', '') + (ac.get('joinphrase', '') if 'joinphrase' in ac else '')
                            for ac in track_artist_credit
                        )
                    else:
                        ta = None

                    recording = t.get('recording', {})
                    tracks.append({
                        'position': t.get('position'),
                        'title': t.get('title', 'Unknown'),
                        'length': t.get('length'),
                        'artist': ta
                    })

            result = {
                'title': data.get('title', 'Unknown'),
                'artist': artist_name_str or 'Unknown',
                'date': data.get('date', 'Unknown'),
                'country': data.get('country', 'Unknown'),
                'status': data.get('status', ''),
                'track_count': len(tracks),
                'tracks': tracks
            }

            logger.info(f"Retrieved {len(tracks)} tracks for {result['title']}")
            return result

        logger.warning(f"No tracks found for release: {release_id}")
        return None

    def search_track(self, track_name: str, artist_name: Optional[str] = None) -> Optional[Dict]:
        """
        Search for a specific recording/track by name and optionally artist.

        Returns:
            Dict with track info including length, artist, and release it appears on or None
        """
        query = f'recording:"{track_name}"'
        if artist_name:
            query += f' AND artist:"{artist_name}"'

        logger.info(f"Searching MusicBrainz for track: {track_name}" + (f" by {artist_name}" if artist_name else ""))

        params = {
            'query': query,
            'limit': 3
        }

        data = self._make_request('/recording/', params)

        if data and data.get('recordings'):
            rec = data['recordings'][0]

            artist_credit = rec.get('artist-credit', [])
            artist_name_str = ''.join(
                ac.get('name', '') + (ac.get('joinphrase', '') if 'joinphrase' in ac else '')
                for ac in artist_credit
            )

            releases = []
            for rel in rec.get('releases', [])[:3]:
                releases.append({
                    'title': rel.get('title', 'Unknown'),
                    'id': rel.get('id', ''),
                    'status': rel.get('status', ''),
                    'date': rel.get('date', '')
                })

            result = {
                'title': rec.get('title', 'Unknown'),
                'id': rec.get('id', ''),
                'artist': artist_name_str or 'Unknown',
                'length': rec.get('length'),
                'releases': releases,
                'total_results': len(data.get('recordings', []))
            }

            logger.info(f"Found track: {result['title']} by {result['artist']}")
            return result

        logger.warning(f"No track found for: {track_name}")
        return None

    def batch_search(self, queries: List[Dict[str, str]]) -> List[Dict]:
        """
        Perform multiple searches in batch.

        Args:
            queries: List of query dicts with 'type' (artist/release/release_group/track) and 'name' keys,
                     optional 'artist' key for context filtering.

        Returns:
            List of results matching the query order
        """
        results = []

        for query in queries:
            query_type = query.get('type', 'release').lower()
            name = query.get('name', '')
            artist = query.get('artist')

            if not name:
                results.append(None)
                continue

            if query_type == 'artist':
                result = self.search_artist(name)
            elif query_type == 'release_group':
                result = self.search_release_group(name, artist)
            elif query_type == 'track':
                result = self.search_track(name, artist)
            else:
                result = self.search_release(name, artist)

            results.append(result)

        return results


def format_musicbrainz_response(result: Optional[Dict], query_type: str = 'release') -> str:
    """
    Format MusicBrainz API result as a natural language response for AI tool use.

    Args:
        result: Result from MusicBrainz search
        query_type: Type of query ('artist', 'release', 'release_group', 'track', or 'tracks')

    Returns:
        Formatted string response
    """
    if not result:
        return "No results found in MusicBrainz."

    if query_type == 'artist':
        response = (f"Artist: {result['name']}\n"
                    f"Type: {result.get('type', 'Unknown')}\n"
                    f"Country: {result.get('country', 'Unknown')}\n"
                    f"Active: {result.get('life_span', 'Unknown')}")
        if result.get('disambiguation'):
            response += f"\nNote: {result['disambiguation']}"
        if result.get('tags'):
            response += f"\nTags: {', '.join(result['tags'][:5])}"
        response += f"\nMusicBrainz ID: {result.get('id', 'N/A')}"
        return response

    elif query_type == 'release':
        response = (f"Release: {result['title']}\n"
                    f"Artist: {result['artist']}\n"
                    f"Release Date: {result.get('date', 'Unknown')}\n"
                    f"Country: {result.get('country', 'Unknown')}\n"
                    f"Status: {result.get('status', 'Unknown')}\n"
                    f"Track Count: {result.get('track_count', 'N/A')}\n"
                    f"MusicBrainz ID: {result.get('id', 'N/A')}")
        return response

    elif query_type == 'release_group':
        response = (f"Album: {result['title']}\n"
                    f"Artist: {result['artist']}\n"
                    f"First Release Date: {result.get('first_release_date', 'Unknown')}\n"
                    f"Type: {result.get('type', 'Unknown')}")
        if result.get('secondary_types'):
            response += f"\nSecondary Types: {', '.join(result['secondary_types'])}"
        if result.get('tags'):
            response += f"\nTags: {', '.join(result['tags'][:5])}"
        response += f"\nMusicBrainz ID: {result.get('id', 'N/A')}"
        return response

    elif query_type == 'track':
        length_ms = result.get('length')
        if length_ms:
            mins = length_ms // 60000
            secs = (length_ms % 60000) // 1000
            length_str = f"{mins}:{secs:02d}"
        else:
            length_str = 'Unknown'

        response = (f"Track: {result['title']}\n"
                    f"Artist: {result['artist']}\n"
                    f"Length: {length_str}\n"
                    f"MusicBrainz ID: {result.get('id', 'N/A')}")
        if result.get('releases'):
            response += "\nAppears on:"
            for rel in result['releases'][:3]:
                response += f"\n  - {rel['title']} ({rel.get('date', 'Unknown')}, {rel.get('status', '')})"
        return response

    elif query_type == 'tracks':
        response = (f"Album: {result['title']}\n"
                    f"Artist: {result['artist']}\n"
                    f"Release Date: {result.get('date', 'Unknown')}\n"
                    f"Tracks ({result.get('track_count', 0)}):\n")

        for track in result.get('tracks', [])[:50]:
            pos = track.get('position', '?')
            title = track.get('title', 'Unknown')
            length_ms = track.get('length')
            if length_ms:
                mins = length_ms // 60000
                secs = (length_ms % 60000) // 1000
                length_str = f"{mins}:{secs:02d}"
            else:
                length_str = ''

            track_artist = track.get('artist')
            artist_str = f" - {track_artist}" if track_artist else ""
            length_display = f" [{length_str}]" if length_str else ""
            response += f"  {pos}. {title}{artist_str}{length_display}\n"

        return response

    return str(result)