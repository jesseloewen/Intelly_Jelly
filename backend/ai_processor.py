import json
import logging
import os
import requests
import time
from typing import List, Dict, Optional, Callable
from openai import OpenAI
from backend.tmdb_api import TMDBClient, format_tool_response
from backend.openlibrary_api import OpenLibraryClient, format_openlibrary_response
from backend.comicvine_api import ComicVineClient, format_comicvine_response
from backend.job_store import JobStatus

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class AIProcessor:
    def __init__(self, config_manager, library_browser=None, job_store=None):
        self.config_manager = config_manager
        self.library_browser = library_browser
        self.job_store = job_store
        self.last_api_call_time = 0
        self.openai_client = None
        self.openrouter_client = None
        self.tmdb_client = None
        self.openlibrary_client = None
        self.comicvine_client = None
        
        self.GOOGLE_MODELS = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "custom"
        ]
        
        self.OPENAI_MODELS = [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "custom"
        ]
        
        self.OPENROUTER_MODELS = [
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-v4-flash",
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
            "custom"
        ]
        
        self.ollama_models_cache = []
        self.ollama_models_cache_time = 0

    def _get_tmdb_client(self) -> Optional[TMDBClient]:
        """Get or initialize TMDB client if enabled and configured."""
        tmdb_enabled = self.config_manager.get('ENABLE_TMDB_TOOL', False)
        if not tmdb_enabled:
            return None
        
        api_key = self.config_manager.get('TMDB_API_KEY', '')
        if not api_key:
            logger.warning("TMDB tool is enabled but TMDB_API_KEY is not configured")
            return None
        
        # Initialize or reuse client
        if not self.tmdb_client:
            self.tmdb_client = TMDBClient(api_key)
            logger.info("Initialized TMDB client")
        
        return self.tmdb_client
    
    def _get_openlibrary_client(self) -> Optional[OpenLibraryClient]:
        """Get or initialize Open Library client if enabled."""
        ol_enabled = self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False)
        if not ol_enabled:
            return None
        
        if not self.openlibrary_client:
            self.openlibrary_client = OpenLibraryClient()
            logger.info("Initialized Open Library client")
        
        return self.openlibrary_client
    
    def _get_comicvine_client(self) -> Optional[ComicVineClient]:
        """Get or initialize Comic Vine client if enabled and configured."""
        cv_enabled = self.config_manager.get('ENABLE_COMICVINE_TOOL', False)
        if not cv_enabled:
            return None
        
        api_key = self.config_manager.get('COMICVINE_API_KEY', '')
        if not api_key:
            logger.warning("Comic Vine tool is enabled but COMICVINE_API_KEY is not configured")
            return None
        
        if not self.comicvine_client:
            self.comicvine_client = ComicVineClient(api_key)
            logger.info("Initialized Comic Vine client")
        
        return self.comicvine_client
    
    def _get_tmdb_tool_definition_google(self) -> Optional[Dict]:
        """Get TMDB tool definition for Google AI function calling."""
        if not self._get_tmdb_client():
            return None
        
        return {
            "function_declarations": [
                {
                    "name": "search_movie",
                    "description": "Search for a movie in The Movie Database (TMDB) to get accurate title, release year, and other metadata. Use this when you need to verify movie information or find release years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "movie_name": {
                                "type": "string",
                                "description": "The name of the movie to search for"
                            }
                        },
                        "required": ["movie_name"]
                    }
                },
                {
                    "name": "search_tv_show",
                    "description": "Search for a TV show in The Movie Database (TMDB) to get accurate title, first air year, and other metadata. Use this when you need to verify TV show information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tv_show_name": {
                                "type": "string",
                                "description": "The name of the TV show to search for"
                            }
                        },
                        "required": ["tv_show_name"]
                    }
                },
                {
                    "name": "get_tv_episode_info",
                    "description": "Get detailed episode information for a specific TV show season, including episode titles and air dates. Use this to get accurate episode names and numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tv_show_name": {
                                "type": "string",
                                "description": "The name of the TV show"
                            },
                            "season_number": {
                                "type": "integer",
                                "description": "The season number"
                            },
                            "episode_number": {
                                "type": "integer",
                                "description": "Optional specific episode number. If omitted, returns all episodes in the season."
                            }
                        },
                        "required": ["tv_show_name", "season_number"]
                    }
                }
            ]
        }
    
    def _get_openlibrary_tool_definition_google(self) -> Optional[Dict]:
        """Get Open Library tool definitions for Google AI function calling."""
        if not self._get_openlibrary_client():
            return None
        
        return {
            "function_declarations": [
                {
                    "name": "search_book",
                    "description": "Search for a book in Open Library to get accurate title, author, and first publish year. Use this when you need to verify book/ebook/audiobook information or find author names and publication years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the book to search for"
                            }
                        },
                        "required": ["book_name"]
                    }
                },
                {
                    "name": "search_audiobook",
                    "description": "Search for an audiobook in Open Library to get accurate title, author, and publication metadata. Use this when the file appears to be an audiobook (audio files in a book-like structure).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the audiobook to search for"
                            }
                        },
                        "required": ["book_name"]
                    }
                },
                {
                    "name": "get_book_chapters",
                    "description": "Get detailed book information including description and subjects from Open Library. Use this to verify book title, author, and get contextual metadata for proper naming.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the book to get details for"
                            }
                        },
                        "required": ["book_name"]
                    }
                },
                {
                    "name": "search_author",
                    "description": "Search for an author in Open Library to get their name, birth date, and notable works. Use this when you need to verify an author's name for book organization.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "author_name": {
                                "type": "string",
                                "description": "The name of the author to search for"
                            }
                        },
                        "required": ["author_name"]
                    }
                }
            ]
        }
    
    def _get_tmdb_tools_for_openai(self) -> List[Dict]:
        """Get TMDB tool definitions for OpenAI function calling."""
        if not self._get_tmdb_client():
            return []
        
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_movie",
                    "description": "Search for a movie in The Movie Database (TMDB) to get accurate title, release year, and other metadata. Use this when you need to verify movie information or find release years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "movie_name": {
                                "type": "string",
                                "description": "The name of the movie to search for"
                            }
                        },
                        "required": ["movie_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_tv_show",
                    "description": "Search for a TV show in The Movie Database (TMDB) to get accurate title, first air year, and other metadata. Use this when you need to verify TV show information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tv_show_name": {
                                "type": "string",
                                "description": "The name of the TV show to search for"
                            }
                        },
                        "required": ["tv_show_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_tv_episode_info",
                    "description": "Get detailed episode information for a specific TV show season, including episode titles and air dates. Use this to get accurate episode names and numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tv_show_name": {
                                "type": "string",
                                "description": "The name of the TV show"
                            },
                            "season_number": {
                                "type": "integer",
                                "description": "The season number"
                            },
                            "episode_number": {
                                "type": "integer",
                                "description": "Optional specific episode number. If omitted, returns all episodes in the season."
                            }
                        },
                        "required": ["tv_show_name", "season_number"]
                    }
                }
            }
        ]
    
    def _get_openlibrary_tools_for_openai(self) -> List[Dict]:
        """Get Open Library tool definitions for OpenAI/OpenRouter function calling."""
        if not self._get_openlibrary_client():
            return []
        
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_book",
                    "description": "Search for a book in Open Library to get accurate title, author, and first publish year. Use this when you need to verify book/ebook/audiobook information or find author names and publication years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the book to search for"
                            }
                        },
                        "required": ["book_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_audiobook",
                    "description": "Search for an audiobook in Open Library to get accurate title, author, and publication metadata. Use this when the file appears to be an audiobook (audio files in a book-like structure).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the audiobook to search for"
                            }
                        },
                        "required": ["book_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_book_chapters",
                    "description": "Get detailed book information including description and subjects from Open Library. Use this to verify book title, author, and get contextual metadata for proper naming.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "book_name": {
                                "type": "string",
                                "description": "The title of the book to get details for"
                            }
                        },
                        "required": ["book_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_author",
                    "description": "Search for an author in Open Library to get their name, birth date, and notable works. Use this when you need to verify an author's name for book organization.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "author_name": {
                                "type": "string",
                                "description": "The name of the author to search for"
                            }
                        },
                        "required": ["author_name"]
                    }
                }
            }
        ]
    
    def _get_comicvine_tool_definition_google(self) -> Optional[Dict]:
        """Get Comic Vine tool definitions for Google AI function calling."""
        if not self._get_comicvine_client():
            return None
        
        return {
            "function_declarations": [
                {
                    "name": "search_comic_volume",
                    "description": "Search for a comic book volume/series in Comic Vine to get accurate title, start year, publisher, and issue count. Use this when you need to verify comic series information or find start years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "volume_name": {
                                "type": "string",
                                "description": "The name of the comic volume/series to search for"
                            }
                        },
                        "required": ["volume_name"]
                    }
                },
                {
                    "name": "search_comic_issue",
                    "description": "Search for a specific comic book issue in Comic Vine to get accurate issue number, cover date, and the volume it belongs to. Use this to identify specific issues from filenames that include issue numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_name": {
                                "type": "string",
                                "description": "The name of the comic issue to search for (can include volume name and issue number, e.g., 'Batman #1')"
                            }
                        },
                        "required": ["issue_name"]
                    }
                }
            ]
        }
    
    def _get_comicvine_tools_for_openai(self) -> List[Dict]:
        """Get Comic Vine tool definitions for OpenAI/OpenRouter function calling."""
        if not self._get_comicvine_client():
            return []
        
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_comic_volume",
                    "description": "Search for a comic book volume/series in Comic Vine to get accurate title, start year, publisher, and issue count. Use this when you need to verify comic series information or find start years.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "volume_name": {
                                "type": "string",
                                "description": "The name of the comic volume/series to search for"
                            }
                        },
                        "required": ["volume_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_comic_issue",
                    "description": "Search for a specific comic book issue in Comic Vine to get accurate issue number, cover date, and the volume it belongs to. Use this to identify specific issues from filenames that include issue numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_name": {
                                "type": "string",
                                "description": "The name of the comic issue to search for (can include volume name and issue number, e.g., 'Batman #1')"
                            }
                        },
                        "required": ["issue_name"]
                    }
                }
            }
        ]
    
    def _get_library_tool_definition_google(self) -> Optional[Dict]:
        if not self.library_browser:
            return None
        return {
            "function_declarations": [
                {
                    "name": "search_library",
                    "description": "Search the media library for existing files and folders. Use this to check for duplicates, verify existing folder structures, or find similarly-named files before suggesting a name. Returns matching filenames and paths. Use the category parameter to narrow results to a specific media type.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to match against filenames and paths in the library"
                            },
                            "category": {
                                "type": "string",
                                "description": "Optional. Narrow search to a specific folder. Category to folder mapping: 'movies'→Movies/, 'tv'→TV Shows/, 'music'→Music/, 'books'→Books/Books/, 'audiobooks'→Books/Audiobooks/, 'comics'→Books/Comics/, 'software'→Software/, 'other'→Other/. Omit to search everywhere."
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
        }
    
    def _get_library_tools_for_openai(self) -> List[Dict]:
        if not self.library_browser:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_library",
                    "description": "Search the media library for existing files and folders. Use this to check for duplicates, verify existing folder structures, or find similarly-named files before suggesting a name. Returns matching filenames and paths. Use the category parameter to narrow results to a specific media type.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to match against filenames and paths in the library"
                            },
                            "category": {
                                "type": "string",
                                "description": "Optional. Narrow search to a specific folder. Category to folder mapping: 'movies'→Movies/, 'tv'→TV Shows/, 'music'→Music/, 'books'→Books/Books/, 'audiobooks'→Books/Audiobooks/, 'comics'→Books/Comics/, 'software'→Software/, 'other'→Other/. Omit to search everywhere."
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]
    
    def _get_pending_tool_definition_google(self) -> Optional[Dict]:
        if not self.job_store:
            return None
        return {
            "function_declarations": [
                {
                    "name": "search_pending_jobs",
                    "description": "Search currently pending AI-generated file names. Use this to ensure naming consistency with other files that are waiting to be organized. For example, check how other episodes of the same TV show have been named.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to match against pending file paths and AI-generated names"
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
        }
    
    def _get_pending_tools_for_openai(self) -> List[Dict]:
        if not self.job_store:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_pending_jobs",
                    "description": "Search currently pending AI-generated file names. Use this to ensure naming consistency with other files that are waiting to be organized. For example, check how other episodes of the same TV show have been named.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to match against pending file paths and AI-generated names"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    def _get_search_queue_tool_definition_google(self) -> Optional[Dict]:
        if not self.job_store:
            return None
        return {
            "function_declarations": [
                {
                    "name": "search_queue",
                    "description": "Search ALL jobs currently in the processing queue (queued, processing, agent-named, pending completion). Use this to find related files that should be processed together in a batch - e.g., other episodes of the same TV season, other chapters of a book, or files with the same base name but different extensions (like .mkv + .srt or .pdf + .epub). This is the primary tool for discovering files to batch-process.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to find related files. Use the show name, book title, base filename, or part of a path. Use empty string '' to list all queued files."
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum results to return (default 30)"
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
        }

    def _get_search_queue_tools_for_openai(self) -> List[Dict]:
        if not self.job_store:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_queue",
                    "description": "Search ALL jobs currently in the processing queue (queued, processing, agent-named, pending completion). Use this to find related files that should be processed together in a batch - e.g., other episodes of the same TV season, other chapters of a book, or files with the same base name but different extensions (like .mkv + .srt or .pdf + .epub). This is the primary tool for discovering files to batch-process.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to find related files. Use the show name, book title, base filename, or part of a path. Use empty string '' to list all queued files."
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum results to return (default 30)"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    def _get_set_name_tool_definition_google(self) -> Dict:
        return {
            "function_declarations": [
                {
                    "name": "set_name",
                    "description": "Set the final destination name and path for a specific file. Call this for EACH file in your batch after you have determined its correct name. The suggested_name must follow the exact naming conventions (e.g., 'TV Shows/Show Name (Year)/Season XX/Show Name (Year) - SXXEYY - Episode Name.ext'). After naming all files in the batch, call finish_group.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "original_path": {
                                "type": "string",
                                "description": "The exact original file path (relative_path) from the input or search results"
                            },
                            "suggested_name": {
                                "type": "string",
                                "description": "The full destination path including category, folders, and filename. Must follow the naming conventions exactly."
                            },
                            "confidence": {
                                "type": "integer",
                                "description": "Confidence score from 0 to 100"
                            }
                        },
                        "required": ["original_path", "suggested_name", "confidence"]
                    }
                }
            ]
        }

    def _get_set_name_tools_for_openai(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "set_name",
                    "description": "Set the final destination name and path for a specific file. Call this for EACH file in your batch after you have determined its correct name. The suggested_name must follow the exact naming conventions (e.g., 'TV Shows/Show Name (Year)/Season XX/Show Name (Year) - SXXEYY - Episode Name.ext'). After naming all files in the batch, call finish_group.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "original_path": {
                                "type": "string",
                                "description": "The exact original file path (relative_path) from the input or search results"
                            },
                            "suggested_name": {
                                "type": "string",
                                "description": "The full destination path including category, folders, and filename. Must follow the naming conventions exactly."
                            },
                            "confidence": {
                                "type": "integer",
                                "description": "Confidence score from 0 to 100"
                            }
                        },
                        "required": ["original_path", "suggested_name", "confidence"]
                    }
                }
            }
        ]

    def _get_finish_group_tool_definition_google(self) -> Dict:
        return {
            "function_declarations": [
                {
                    "name": "finish_group",
                    "description": "Mark the current batch of files as complete. Call this ONCE after you have used set_name for every file in the batch. This finalizes all files and transitions them to pending completion so they can be moved to the library. Do NOT call this until ALL files in the batch have been named.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "note": {
                                "type": "string",
                                "description": "Optional summary note about what was processed (e.g., 'Named 10 episodes of The Office S01')"
                            }
                        },
                        "required": []
                    }
                }
            ]
        }

    def _get_finish_group_tools_for_openai(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "finish_group",
                    "description": "Mark the current batch of files as complete. Call this ONCE after you have used set_name for every file in the batch. This finalizes all files and transitions them to pending completion so they can be moved to the library. Do NOT call this until ALL files in the batch have been named.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "note": {
                                "type": "string",
                                "description": "Optional summary note about what was processed (e.g., 'Named 10 episodes of The Office S01')"
                            }
                        },
                        "required": []
                    }
                }
            }
        ]

    def _get_smart_group_tool_definition_google(self) -> Optional[Dict]:
        if not self.job_store:
            return None
        return {
            "function_declarations": [
                {
                    "name": "smart_group",
                    "description": "Dynamically group related queued files into the current processing batch. Use this to pull in additional files you discover are related (same TV show season, same book, same movie with subtitles). The system will add them to your current batch so you can name them all together.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of job_ids to add to the current batch"
                            }
                        },
                        "required": ["job_ids"]
                    }
                }
            ]
        }

    def _get_smart_group_tools_for_openai(self) -> List[Dict]:
        if not self.job_store:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "smart_group",
                    "description": "Dynamically group related queued files into the current processing batch. Use this to pull in additional files you discover are related (same TV show season, same book, same movie with subtitles). The system will add them to your current batch so you can name them all together.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of job_ids to add to the current batch"
                            }
                        },
                        "required": ["job_ids"]
                    }
                }
            }
        ]
    
    def _execute_tmdb_function(self, function_name: str, args: Dict) -> str:
        """Execute a TMDB or Open Library function call and return formatted response."""
        client = self._get_tmdb_client()
        
        try:
            if function_name == "search_movie":
                if not client:
                    return "TMDB tool is not available"
                result = client.search_movie(args.get("movie_name", ""))
                return format_tool_response(result, "movie")
            
            elif function_name == "search_tv_show":
                if not client:
                    return "TMDB tool is not available"
                result = client.search_tv_show(args.get("tv_show_name", ""))
                return format_tool_response(result, "tv")
            
            elif function_name == "get_tv_episode_info":
                if not client:
                    return "TMDB tool is not available"
                result = client.get_tv_episode_info(
                    args.get("tv_show_name", ""),
                    args.get("season_number", 1),
                    args.get("episode_number")
                )
                return format_tool_response(result, "episode")
            
            elif function_name in ("search_book", "search_audiobook", "get_book_chapters", "search_author"):
                ol_client = self._get_openlibrary_client()
                if not ol_client:
                    return "Open Library tool is not available"
                
                if function_name == "search_book":
                    result = ol_client.search_book(args.get("book_name", ""))
                    return format_openlibrary_response(result, "book")
                
                elif function_name == "search_audiobook":
                    result = ol_client.search_audiobook(args.get("book_name", ""))
                    return format_openlibrary_response(result, "audiobook")
                
                elif function_name == "get_book_chapters":
                    result = ol_client.get_book_chapters(args.get("book_name", ""))
                    return format_openlibrary_response(result, "chapters")
                
                elif function_name == "search_author":
                    result = ol_client.search_author(args.get("author_name", ""))
                    return format_openlibrary_response(result, "author")
            
            elif function_name in ("search_comic_volume", "search_comic_issue"):
                cv_client = self._get_comicvine_client()
                if not cv_client:
                    return "Comic Vine tool is not available"
                
                if function_name == "search_comic_volume":
                    result = cv_client.search_volume(args.get("volume_name", ""))
                    return format_comicvine_response(result, "volume")
                
                elif function_name == "search_comic_issue":
                    result = cv_client.search_issue(args.get("issue_name", ""))
                    return format_comicvine_response(result, "issue")
            
            elif function_name == "search_library":
                if not self.library_browser:
                    return "Library search tool is not available"
                if not os.path.exists(self.library_browser.library_path):
                    return "Library path does not exist"
                results = self.library_browser.search_library(
                    args.get("query", ""),
                    category=args.get("category"),
                    max_results=20
                )
                if not results:
                    return "No matching files found in library"
                return json.dumps(results, indent=2)
            
            elif function_name == "search_pending_jobs":
                if not self.job_store:
                    return "Pending jobs search tool is not available"
                results = self.job_store.search_pending_jobs(
                    args.get("query", ""),
                    max_results=15
                )
                if not results:
                    return "No matching pending jobs found"
                return json.dumps(results, indent=2)

            elif function_name == "search_queue":
                if not self.job_store:
                    return "Queue search tool is not available"
                results = self.job_store.search_queue(
                    args.get("query", ""),
                    max_results=args.get("max_results", 30)
                )
                if not results:
                    return "No matching queued files found"
                return json.dumps(results, indent=2)

            elif function_name == "smart_group":
                if not self.job_store:
                    return "Smart grouping tool is not available"
                job_ids = args.get("job_ids", [])
                if not job_ids:
                    return "No job_ids provided for smart_group"
                result = self.job_store.smart_group_jobs("", job_ids=job_ids)
                return json.dumps(result, indent=2)

            elif function_name == "set_name":
                if not self.job_store:
                    return "Set name tool is not available"
                original_path = args.get("original_path", "")
                suggested_name = args.get("suggested_name", "")
                confidence = args.get("confidence", 0)
                job = self.job_store.get_job_by_path(original_path)
                if not job:
                    return json.dumps({"error": f"No queued job found for path: {original_path}", "status": "not_found"})
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.AGENT_NAMED,
                    suggested_name=suggested_name,
                    confidence=confidence,
                )
                return json.dumps({"status": "ok", "job_id": job.job_id, "named": os.path.basename(original_path)})

            elif function_name == "finish_group":
                return json.dumps({"status": "finish_group_requested", "note": args.get("note", "")})
            
            else:
                return f"Unknown function: {function_name}"
        
        except Exception as e:
            logger.error(f"Error executing function {function_name}: {e}")
            return f"Error: {str(e)}"
    
    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract valid JSON array/object from text that may contain surrounding commentary.
        
        Uses json.JSONDecoder.raw_decode() which correctly handles brackets inside
        JSON strings and returns the position where valid JSON ends.
        """
        text = text.strip()
        if text.startswith('```json'):
            text = text[7:]
        elif text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        
        if not text:
            return text
        
        # Find the first [ or {
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch in ('[', '{'):
                try:
                    obj, end = decoder.raw_decode(text[i:])
                    return text[i:i + end]
                except json.JSONDecodeError:
                    continue
        
        return text
    
    def _parse_ai_response(self, text: str, log_prefix: str, on_event: Optional[Callable] = None) -> List[Dict]:
        """Shared response parser for all AI providers.
        
        Handles: code fence stripping, JSON extraction, parsing both
        {'files': [...]} and direct list formats, event emission, and error handling.
        
        Args:
            text: Raw response text from the AI provider.
            log_prefix: Provider name for log messages (e.g., 'Google', 'OpenAI').
            on_event: Optional SSE event callback.
            
        Returns:
            List of result dicts with original_path, suggested_name, confidence.
            Returns empty list on failure.
        """
        text = text.strip()
        text = self._extract_json(text)
        
        logger.debug(f"[{log_prefix}] Parsing AI response as JSON")
        
        if not text:
            logger.warning(f"[{log_prefix}] Empty response text after extraction")
            return []
        
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[{log_prefix}] Failed to parse JSON response: {e}")
            logger.error(f"[{log_prefix}] Raw text (first 500 chars): {text[:500]}")
            return []
        
        if isinstance(result, dict) and 'files' in result:
            files = result['files']
            logger.info(f"[{log_prefix}] AI processing completed: {len(files)} results from wrapped dict")
            if on_event and files:
                first = files[0]
                on_event({"type": "result", "confidence": first.get('confidence', 0), "file_count": len(files)})
            return files
        elif isinstance(result, list):
            logger.info(f"[{log_prefix}] AI processing completed: {len(result)} results from direct list")
            if on_event and result:
                first_confidence = result[0].get('confidence', 0) if isinstance(result[0], dict) else 0
                on_event({"type": "result", "confidence": first_confidence, "file_count": len(result)})
            return result
        else:
            logger.warning(f"[{log_prefix}] AI response in unexpected format, returning empty list")
            return []
    
    def _get_instructions(self) -> str:
        # Check for custom instructions first, fall back to base instructions
        custom_path = './instruction_prompt_custom.md'
        base_path = './instruction_prompt.md'
        instructions_path = custom_path if os.path.exists(custom_path) else base_path
        
        try:
            with open(instructions_path, 'r', encoding='utf-8') as f:
                content = f.read()
                logger.info(f"Loaded instructions from {instructions_path}")
                return content
        except FileNotFoundError:
            logger.warning(f"Instructions file not found at {instructions_path}, using default instructions")
            return "Suggest improved file names for the following files. Return JSON array with original_path, suggested_name, and confidence (0-100)."
        except UnicodeDecodeError as e:
            logger.error(f"Unicode decode error reading {instructions_path}: {e}")
            logger.warning("Using default instructions instead")
            return "Suggest improved file names for the following files. Return JSON array with original_path, suggested_name, and confidence (0-100)."

    def _prepare_batch_prompt(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True) -> str:
        base_instructions = self._get_instructions() if include_default else ""
        
        if custom_prompt:
            prompt = f"{base_instructions}\n\nAdditional instructions: {custom_prompt}\n\n"
        else:
            prompt = f"{base_instructions}\n\n"
        
        if include_filename:
            prompt += "Files to process:\n"
            for path in file_paths:
                prompt += f"- {path}\n"
        else:
            prompt += f"Number of files to process: {len(file_paths)}\n"
        
        return prompt

    def process_single(self, file_path: str, custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, enable_search_queue_tool: bool = False, enable_agent_tools: bool = False, on_event: Optional[Callable] = None) -> Optional[Dict]:
        """Process a single file using configured AI with optional web search and tools."""
        logger.info(f"Starting AI processing for file: {file_path}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}, OpenLibrary tool: {enable_openlibrary_tool}, ComicVine tool: {enable_comicvine_tool}, Library tool: {enable_library_tool}, Pending tool: {enable_pending_tool}, Search Queue: {enable_search_queue_tool}, Agent: {enable_agent_tools}")
        
        results = self.process_batch([file_path], custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool, enable_openlibrary_tool, enable_comicvine_tool, enable_library_tool, enable_pending_tool, enable_search_queue_tool, enable_agent_tools, on_event=on_event)
        return results[0] if results else None
    
    def process_batch(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, enable_search_queue_tool: bool = False, enable_agent_tools: bool = False, on_event: Optional[Callable] = None) -> List[Dict]:
        """Process files using configured AI provider with optional web search and tools."""
        logger.info(f"Starting AI processing for {len(file_paths)} file(s)")
        logger.debug(f"Files to process: {file_paths}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}, OpenLibrary tool: {enable_openlibrary_tool}, ComicVine tool: {enable_comicvine_tool}, Library tool: {enable_library_tool}, Pending tool: {enable_pending_tool}, Search Queue: {enable_search_queue_tool}, Agent: {enable_agent_tools}")
        
        # Override enable_tmdb_tool based on actual config state (if not explicitly disabled)
        if enable_tmdb_tool:
            tmdb_enabled_in_config = self.config_manager.get('ENABLE_TMDB_TOOL', False)
            if not tmdb_enabled_in_config:
                logger.warning("TMDB tool requested but not enabled in config, disabling for this request")
                enable_tmdb_tool = False
        
        if enable_openlibrary_tool:
            ol_enabled_in_config = self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False)
            if not ol_enabled_in_config:
                logger.warning("Open Library tool requested but not enabled in config, disabling for this request")
                enable_openlibrary_tool = False
        
        if enable_comicvine_tool:
            cv_enabled_in_config = self.config_manager.get('ENABLE_COMICVINE_TOOL', False)
            if not cv_enabled_in_config:
                logger.warning("Comic Vine tool requested but not enabled in config, disabling for this request")
                enable_comicvine_tool = False
        
        if enable_library_tool:
            library_enabled_in_config = self.config_manager.get('ENABLE_LIBRARY_TOOL', False)
            if not library_enabled_in_config:
                logger.warning("Library tool requested but not enabled in config, disabling for this request")
                enable_library_tool = False
        
        if enable_pending_tool:
            pending_enabled_in_config = self.config_manager.get('ENABLE_PENDING_TOOL', False)
            if not pending_enabled_in_config:
                logger.warning("Pending tool requested but not enabled in config, disabling for this request")
                enable_pending_tool = False
        
        provider = self.config_manager.get('AI_PROVIDER', 'google')
        logger.info(f"Using AI provider: {provider}")
        
        if provider == 'openai':
            return self._process_batch_openai(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool, enable_openlibrary_tool, enable_comicvine_tool, enable_library_tool, enable_pending_tool, enable_search_queue_tool, enable_agent_tools, on_event=on_event)
        elif provider == "openrouter":
            return self._process_batch_openrouter(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool, enable_openlibrary_tool, enable_comicvine_tool, enable_library_tool, enable_pending_tool, enable_search_queue_tool, enable_agent_tools, on_event=on_event)
        elif provider == "ollama":
            return self._process_batch_ollama(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool, enable_openlibrary_tool, enable_comicvine_tool, enable_library_tool, enable_pending_tool, enable_search_queue_tool, enable_agent_tools, on_event=on_event)
        elif provider == "google" or provider == "custom":
            return self._process_batch_google(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool, enable_openlibrary_tool, enable_comicvine_tool, enable_library_tool, enable_pending_tool, enable_search_queue_tool, enable_agent_tools, on_event=on_event)
    
    def _process_batch_google(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, on_event: Optional[Callable] = None) -> List[Dict]:
        """Process files using Google AI with optional web search and tools."""
        api_key = self.config_manager.get('GOOGLE_API_KEY', '')
        if not api_key:
            logger.error("GOOGLE_API_KEY not found in configuration")
            raise ValueError("GOOGLE_API_KEY not set. Please configure it in Settings.")
        
        model = self.config_manager.get('AI_MODEL', 'gemini-2.5-flash')
        logger.info(f"Using AI model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        # Get Google AI parameters from config with defaults
        temperature = float(self.config_manager.get('GOOGLE_TEMPERATURE', 0.1))
        max_tokens = int(self.config_manager.get('GOOGLE_MAX_TOKENS', 2048))
        top_k = int(self.config_manager.get('GOOGLE_TOP_K', 1))
        top_p = float(self.config_manager.get('GOOGLE_TOP_P', 1))
        
        # Build base payload
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": temperature,
                "topK": top_k,
                "topP": top_p,
                "maxOutputTokens": max_tokens,
            }
        }
        
        # Add tools if enabled
        tools = []
        if enable_web_search:
            tools.append({"google_search": {}})
        
        if enable_tmdb_tool:
            tmdb_tool = self._get_tmdb_tool_definition_google()
            if tmdb_tool:
                tools.append(tmdb_tool)
        
        if enable_openlibrary_tool:
            ol_tool = self._get_openlibrary_tool_definition_google()
            if ol_tool:
                tools.append(ol_tool)
        
        if enable_comicvine_tool:
            cv_tool = self._get_comicvine_tool_definition_google()
            if cv_tool:
                tools.append(cv_tool)
        
        if enable_library_tool:
            lib_tool = self._get_library_tool_definition_google()
            if lib_tool:
                tools.append(lib_tool)
        
        if enable_pending_tool:
            pend_tool = self._get_pending_tool_definition_google()
            if pend_tool:
                tools.append(pend_tool)
        
        if tools:
            payload["tools"] = tools
        
        try:
            # Enforce delay between API calls
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to Google AI API: {model}")
            
            if on_event:
                tools_active = []
                if enable_web_search: tools_active.append("web_search")
                if enable_tmdb_tool: tools_active.append("tmdb")
                if enable_openlibrary_tool: tools_active.append("openlibrary")
                if enable_comicvine_tool: tools_active.append("comicvine")
                if enable_library_tool: tools_active.append("library")
                if enable_pending_tool: tools_active.append("pending")
                on_event({"type": "api_request", "provider": "google", "model": model, "tools": tools_active})
            
            logger.debug(f"API URL: {url.split('?')[0]}")  # Log URL without API key
            logger.debug(f"Payload config: temperature={payload['generationConfig']['temperature']}, maxTokens={payload['generationConfig']['maxOutputTokens']}")
            
            # Log full request payload (without API key)
            logger.info("=" * 80)
            logger.info("GOOGLE AI API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.debug(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.debug(f"Full Prompt:\n{prompt}")
            logger.debug(f"Generation Config: {json.dumps(payload['generationConfig'], indent=2)}")
            if 'tools' in payload:
                logger.debug(f"Tools: {json.dumps(payload['tools'], indent=2)}")
            logger.info("=" * 80)
            
            # Handle multi-turn conversation for function calling
            conversation_history = payload["contents"].copy()
            max_turns = 30  # Prevent infinite loops
            
            for turn in range(max_turns):
                req_start = time.time()
                response = requests.post(url, json=payload)
                req_duration = int((time.time() - req_start) * 1000)
                self.last_api_call_time = time.time()
                response.raise_for_status()
                
                logger.info(f"Received successful response from Google AI API (status: {response.status_code})")
                
                if on_event:
                    on_event({"type": "api_response", "turn": turn + 1, "duration_ms": req_duration})
                
                # Log full response
                logger.info("=" * 80)
                logger.info(f"GOOGLE AI API RESPONSE (Turn {turn + 1})")
                logger.info("=" * 80)
                logger.info(f"Status Code: {response.status_code}")
                logger.debug(f"Full Response:\n{json.dumps(response.json(), indent=2)}")
                logger.info("=" * 80)
                
                data = response.json()
                candidate = data['candidates'][0]
                parts = candidate['content']['parts']
                
                # Check if there are function calls
                function_calls = [part for part in parts if 'functionCall' in part]
                
                if function_calls:
                    logger.info(f"AI requested {len(function_calls)} function call(s)")
                    
                    # Add AI's response to conversation
                    conversation_history.append(candidate['content'])
                    
                    # Execute each function call and collect responses
                    function_responses = []
                    for fc in function_calls:
                        func_name = fc['functionCall']['name']
                        func_args = fc['functionCall'].get('args', {})
                        
                        logger.debug(f"Executing function: {func_name} with args: {func_args}")
                        if on_event:
                            on_event({"type": "tool_started", "tool": func_name, "args": json.dumps(func_args)})
                        result = self._execute_tmdb_function(func_name, func_args)
                        if on_event:
                            on_event({"type": "tool_completed", "tool": func_name})
                        
                        function_responses.append({
                            "functionResponse": {
                                "name": func_name,
                                "response": {"result": result}
                            }
                        })
                    
                    # Add function responses to conversation and continue
                    conversation_history.append({"parts": function_responses})
                    payload["contents"] = conversation_history
                    
                    # Enforce delay before next API call
                    delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
                    logger.info(f"Waiting {delay_seconds} seconds before next API call")
                    time.sleep(delay_seconds)
                    
                    continue  # Make another API call with function results
                
                # No function calls, extract final text response
                text_parts = [part.get('text', '') for part in parts if 'text' in part]
                if not text_parts:
                    logger.warning("No text in AI response")
                    return []
                
                text = ''.join(text_parts)
                logger.debug(f"Raw AI response length: {len(text)} characters")
                
                return self._parse_ai_response(text, "Google", on_event)
            
            # Max turns reached
            logger.warning(f"Maximum conversation turns ({max_turns}) reached without final answer")
            return []
                
        except requests.exceptions.HTTPError as e:
            logger.error(f"Google API HTTP error: {e}, Status code: {response.status_code if 'response' in locals() else 'N/A'}")
            logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
            if on_event:
                on_event({"type": "error", "message": f"API error: {e}"})
            raise
        except KeyError as e:
            logger.error(f"Unexpected response structure from Google API: {e}")
            logger.error(f"Response data: {data if 'data' in locals() else 'N/A'}")
            if on_event:
                on_event({"type": "error", "message": f"Unexpected API response structure"})
            raise
        except Exception as e:
            logger.error(f"Unexpected error during AI processing: {type(e).__name__}: {e}")
            if on_event:
                on_event({"type": "error", "message": str(e)})
            raise

    def _process_batch_openai(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, on_event: Optional[Callable] = None) -> List[Dict]:
        """Process files using OpenAI with optional web search."""
        api_key = self.config_manager.get('OPENAI_API_KEY', '')
        if not api_key:
            logger.error("OPENAI_API_KEY not found in configuration")
            raise ValueError("OPENAI_API_KEY not set. Please configure it in Settings.")
        
        # Initialize OpenAI client with API key
        if not self.openai_client or os.environ.get('OPENAI_API_KEY') != api_key:
            os.environ['OPENAI_API_KEY'] = api_key
            self.openai_client = OpenAI()
            logger.info("Initialized OpenAI client")
        
        model = self.config_manager.get('AI_MODEL', 'gpt-5-mini')
        logger.info(f"Using OpenAI model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        try:
            # Enforce delay between API calls to avoid rate limiting
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to OpenAI API: {model}")
            
            if on_event:
                tools_active = []
                if enable_web_search: tools_active.append("web_search")
                if enable_tmdb_tool: tools_active.append("tmdb")
                if enable_openlibrary_tool: tools_active.append("openlibrary")
                if enable_comicvine_tool: tools_active.append("comicvine")
                if enable_library_tool: tools_active.append("library")
                if enable_pending_tool: tools_active.append("pending")
                on_event({"type": "api_request", "provider": "openai", "model": model, "tools": tools_active})
            
            # Build tools list - only TMDB supported (web search not available in standard OpenAI API)
            tools = []
            use_chat_api = False
            
            if enable_web_search:
                logger.warning("Web search is not supported with OpenAI API. Consider using Google AI or adding TMDB tool for metadata lookup.")
            
            if enable_tmdb_tool:
                tmdb_tools = self._get_tmdb_tools_for_openai()
                if tmdb_tools:
                    tools.extend(tmdb_tools)
                use_chat_api = True
            
            if enable_openlibrary_tool:
                ol_tools = self._get_openlibrary_tools_for_openai()
                if ol_tools:
                    tools.extend(ol_tools)
                use_chat_api = True
            
            if enable_comicvine_tool:
                cv_tools = self._get_comicvine_tools_for_openai()
                if cv_tools:
                    tools.extend(cv_tools)
                    use_chat_api = True
            
            if enable_library_tool:
                lib_tools = self._get_library_tools_for_openai()
                if lib_tools:
                    tools.extend(lib_tools)
                use_chat_api = True
            
            if enable_pending_tool:
                pend_tools = self._get_pending_tools_for_openai()
                if pend_tools:
                    tools.extend(pend_tools)
                use_chat_api = True
            
            # Log full request
            logger.info("=" * 80)
            logger.info("OPENAI API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.info(f"TMDB Tool Enabled: {enable_tmdb_tool}")
            logger.info(f"API: {'chat.completions' if use_chat_api else 'responses'}")
            logger.debug(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.debug(f"Full Prompt:\n{prompt}")
            if tools:
                logger.debug(f"Tools: {json.dumps(tools, indent=2)}")
            logger.info("=" * 80)
            
            # Get OpenAI parameters from config with defaults
            temperature = float(self.config_manager.get('OPENAI_TEMPERATURE', 0.1))
            max_tokens = int(self.config_manager.get('OPENAI_MAX_TOKENS', 2048))
            top_p = float(self.config_manager.get('OPENAI_TOP_P', 1))
            frequency_penalty = float(self.config_manager.get('OPENAI_FREQUENCY_PENALTY', 0))
            presence_penalty = float(self.config_manager.get('OPENAI_PRESENCE_PENALTY', 0))
            
            # OpenAI's responses API doesn't support function calling/tools
            # Use chat.completions when tools are needed, responses otherwise
            if use_chat_api:
                # Use chat.completions API for function calling support with multi-turn conversation
                messages = [{"role": "user", "content": prompt}]
                max_turns = 30
                turn = 0
                
                while turn < max_turns:
                    turn += 1
                    logger.info(f"OpenAI conversation turn {turn}/{max_turns}")
                    
                    req_start = time.time()
                    response = self.openai_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        temperature=temperature,
                        max_tokens=max_tokens,
                        top_p=top_p,
                        frequency_penalty=frequency_penalty,
                        presence_penalty=presence_penalty
                    )
                    req_duration = int((time.time() - req_start) * 1000)
                    
                    self.last_api_call_time = time.time()
                    message = response.choices[0].message
                    messages.append(message)
                    
                    if on_event:
                        on_event({"type": "api_response", "turn": turn, "duration_ms": req_duration})
                    
                    # Check if AI made tool calls
                    if message.tool_calls:
                        logger.info(f"AI requested {len(message.tool_calls)} tool call(s)")
                        
                        # Execute each tool call
                        for tool_call in message.tool_calls:
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)
                            
                            logger.debug(f"Executing function: {function_name} with args: {function_args}")
                            
                            if on_event:
                                on_event({"type": "tool_started", "tool": function_name, "args": json.dumps(function_args)})
                            
                            function_result = self._execute_tmdb_function(function_name, function_args)
                            
                            if on_event:
                                on_event({"type": "tool_completed", "tool": function_name})
                            
                            # Add function result to messages
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(function_result)
                            })
                            
                            logger.debug(f"Function {function_name} returned: {function_result}")
                        
                        # Continue to next turn to get AI's response with function results
                        continue
                    
                    # No tool calls, check if we have final answer
                    if message.content:
                        text = message.content
                        logger.info(f"Received final response from OpenAI Chat Completions API")
                        break
                    else:
                        logger.warning("No content or tool calls in response")
                        text = "[]"
                        break
                
                if turn >= max_turns:
                    logger.warning(f"Maximum conversation turns ({max_turns}) reached")
                    text = "[]"
            else:
                # Use responses.create API (no tools needed)
                req_start = time.time()
                response = self.openai_client.responses.create(
                    model=model,
                    input=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty
                )
                req_duration = int((time.time() - req_start) * 1000)
                
                self.last_api_call_time = time.time()
                logger.info(f"Received successful response from OpenAI Responses API")
                
                if on_event:
                    on_event({"type": "api_response", "turn": 1, "duration_ms": req_duration})
                
                # Extract the text using output_text
                text = response.output_text
            
            logger.info("=" * 80)
            logger.info("OPENAI API RESPONSE")
            logger.info("=" * 80)
            logger.info(f"Response length: {len(text)} characters")
            logger.debug(f"Full Response:\n{text}")
            logger.info("=" * 80)
            
            return self._parse_ai_response(text, "OpenAI", on_event)
                
        except Exception as e:
            logger.error(f"OpenAI API error: {type(e).__name__}: {e}")
            if on_event:
                on_event({"type": "error", "message": str(e)})
            raise

    def _process_batch_openrouter(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, on_event: Optional[Callable] = None) -> List[Dict]:
        """Process files using OpenRouter (OpenAI-compatible API)."""
        api_key = self.config_manager.get('OPENROUTER_API_KEY', '')
        if not api_key:
            logger.error("OPENROUTER_API_KEY not found in configuration")
            raise ValueError("OPENROUTER_API_KEY not set. Please configure it in Settings.")
        
        if not self.openrouter_client or os.environ.get('OPENROUTER_API_KEY') != api_key:
            self.openrouter_client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=api_key
            )
            logger.info("Initialized OpenRouter client")
        
        model = self.config_manager.get('AI_MODEL', 'deepseek/deepseek-chat')
        logger.info(f"Using OpenRouter model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        try:
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to OpenRouter API: {model}")
            
            if on_event:
                tools_active = []
                if enable_web_search: tools_active.append("web_search")
                if enable_tmdb_tool: tools_active.append("tmdb")
                if enable_openlibrary_tool: tools_active.append("openlibrary")
                if enable_comicvine_tool: tools_active.append("comicvine")
                if enable_library_tool: tools_active.append("library")
                if enable_pending_tool: tools_active.append("pending")
                on_event({"type": "api_request", "provider": "openrouter", "model": model, "tools": tools_active})
            
            tools = []
            use_tools = False
            
            if enable_web_search:
                logger.warning("Web search is not supported with OpenRouter. Consider enabling TMDB tool for metadata lookup.")
            
            if enable_tmdb_tool:
                tmdb_tools = self._get_tmdb_tools_for_openai()
                if tmdb_tools:
                    tools.extend(tmdb_tools)
                    use_tools = True
            
            if enable_openlibrary_tool:
                ol_tools = self._get_openlibrary_tools_for_openai()
                if ol_tools:
                    tools.extend(ol_tools)
                    use_tools = True
            
            if enable_comicvine_tool:
                cv_tools = self._get_comicvine_tools_for_openai()
                if cv_tools:
                    tools.extend(cv_tools)
                    use_tools = True
            
            if enable_library_tool:
                lib_tools = self._get_library_tools_for_openai()
                if lib_tools:
                    tools.extend(lib_tools)
                    use_tools = True
            
            if enable_pending_tool:
                pend_tools = self._get_pending_tools_for_openai()
                if pend_tools:
                    tools.extend(pend_tools)
                    use_tools = True
            
            logger.info("=" * 80)
            logger.info("OPENROUTER API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.info(f"TMDB Tool Enabled: {enable_tmdb_tool}")
            logger.debug(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.debug(f"Full Prompt:\n{prompt}")
            if tools:
                logger.debug(f"Tools: {json.dumps(tools, indent=2)}")
            logger.info("=" * 80)
            
            temperature = float(self.config_manager.get('OPENROUTER_TEMPERATURE', 0.1))
            max_tokens = int(self.config_manager.get('OPENROUTER_MAX_TOKENS', 4096))
            top_p = float(self.config_manager.get('OPENROUTER_TOP_P', 1))
            
            messages = [{"role": "user", "content": prompt}]
            
            if use_tools:
                max_turns = 30
                turn = 0
                
                while turn < max_turns:
                    turn += 1
                    logger.info(f"OpenRouter conversation turn {turn}/{max_turns}")
                    
                    req_start = time.time()
                    response = self.openrouter_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        temperature=temperature,
                        max_tokens=max_tokens,
                        top_p=top_p
                    )
                    req_duration = int((time.time() - req_start) * 1000)
                    
                    self.last_api_call_time = time.time()
                    message = response.choices[0].message
                    messages.append(message)
                    
                    if on_event:
                        on_event({"type": "api_response", "turn": turn, "duration_ms": req_duration})
                    
                    if message.tool_calls:
                        logger.info(f"AI requested {len(message.tool_calls)} tool call(s)")
                        
                        for tool_call in message.tool_calls:
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)
                            
                            logger.debug(f"Executing function: {function_name} with args: {function_args}")
                            if on_event:
                                on_event({"type": "tool_started", "tool": function_name, "args": json.dumps(function_args)})
                            function_result = self._execute_tmdb_function(function_name, function_args)
                            if on_event:
                                on_event({"type": "tool_completed", "tool": function_name})
                            
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(function_result)
                            })
                            
                            logger.debug(f"Function {function_name} returned: {function_result}")
                        
                        continue
                    
                    if message.content:
                        text = message.content
                        logger.info(f"Received final response from OpenRouter API")
                        break
                    elif hasattr(message, 'reasoning_content') and message.reasoning_content:
                        text = message.reasoning_content
                        logger.info(f"Using reasoning_content from OpenRouter response")
                        break
                    else:
                        logger.warning("No content or tool calls in response")
                        text = "[]"
                        break
                
                if turn >= max_turns:
                    logger.warning(f"Maximum conversation turns ({max_turns}) reached")
                    text = "[]"
            else:
                req_start = time.time()
                response = self.openrouter_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p
                )
                req_duration = int((time.time() - req_start) * 1000)
                
                self.last_api_call_time = time.time()
                logger.info(f"Received successful response from OpenRouter API")
                
                if on_event:
                    on_event({"type": "api_response", "turn": 1, "duration_ms": req_duration})
                message = response.choices[0].message
                
                # OpenRouter/DeepSeek may return content in reasoning_content field
                if message.content is not None:
                    text = message.content
                elif hasattr(message, 'reasoning_content') and message.reasoning_content:
                    text = message.reasoning_content
                    logger.info("Using reasoning_content from OpenRouter response")
                else:
                    logger.warning(f"No content in OpenRouter response. Raw message: {message}")
                    text = ""
            
            logger.info("=" * 80)
            logger.info("OPENROUTER API RESPONSE")
            logger.info("=" * 80)
            logger.info(f"Response length: {len(text)} characters")
            logger.debug(f"Full Response:\n{text}")
            logger.info("=" * 80)
            
            return self._parse_ai_response(text, "OpenRouter", on_event)
                
        except Exception as e:
            logger.error(f"OpenRouter API error: {type(e).__name__}: {e}")
            if on_event:
                on_event({"type": "error", "message": str(e)})
            raise

    def get_available_models(self, provider: Optional[str] = None) -> List[str]:
        """Get available models for the specified provider."""
        if not provider:
            provider = self.config_manager.get('AI_PROVIDER', 'google')
        
        logger.info(f"Fetching available models for provider: {provider}")
        
        if provider == 'openai':
            return self.OPENAI_MODELS
        elif provider == 'openrouter':
            return self.OPENROUTER_MODELS
        elif provider == 'ollama':
            return self._get_ollama_models()
        else:
            return self.GOOGLE_MODELS
    
    def _get_ollama_models(self) -> List[str]:
        """Fetch available models from Ollama server."""
        # Cache models for 5 minutes to avoid excessive API calls
        current_time = time.time()
        if self.ollama_models_cache and (current_time - self.ollama_models_cache_time) < 300:
            logger.debug("Returning cached Ollama models")
            return self.ollama_models_cache
        
        base_url = self.config_manager.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        
        try:
            logger.info(f"Fetching available models from Ollama: {base_url}")
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            response.raise_for_status()
            
            data = response.json()
            models = [model['name'] for model in data.get('models', [])]
            
            if not models:
                logger.warning("No models available from Ollama server")
                return ["No models available"]
            
            logger.info(f"Found {len(models)} Ollama models: {models}")
            self.ollama_models_cache = models
            self.ollama_models_cache_time = current_time
            
            return models
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch Ollama models: {e}")
            return ["Error: Cannot connect to Ollama server"]
        except Exception as e:
            logger.error(f"Unexpected error fetching Ollama models: {e}")
            return ["Error: Failed to fetch models"]
    
    def _process_batch_ollama(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False, enable_library_tool: bool = False, enable_pending_tool: bool = False, on_event: Optional[Callable] = None) -> List[Dict]:
        """Process files using Ollama."""
        base_url = self.config_manager.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        if not base_url:
            logger.error("OLLAMA_BASE_URL not found in configuration")
            raise ValueError("OLLAMA_BASE_URL not set. Please configure it in Settings.")
        
        model = self.config_manager.get('AI_MODEL', 'llama3.2')
        logger.info(f"Using Ollama model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        if enable_web_search:
            logger.warning("Web search is not supported with Ollama, ignoring this option")
        
        # Build tools for Ollama (same format as OpenAI)
        if enable_tmdb_tool:
            tmdb_tools = self._get_tmdb_tools_for_openai()
        else:
            tmdb_tools = []
        
        if enable_openlibrary_tool:
            ol_tools = self._get_openlibrary_tools_for_openai()
            if not enable_tmdb_tool and not enable_comicvine_tool:
                tmdb_tools = []
            tmdb_tools.extend(ol_tools)
        elif not enable_tmdb_tool and not enable_comicvine_tool:
            tmdb_tools = []
        
        if enable_comicvine_tool:
            cv_tools = self._get_comicvine_tools_for_openai()
            if not enable_tmdb_tool and not enable_openlibrary_tool:
                tmdb_tools = []
            tmdb_tools.extend(cv_tools)
        
        if enable_library_tool:
            lib_tools = self._get_library_tools_for_openai()
            if not enable_tmdb_tool and not enable_openlibrary_tool and not enable_comicvine_tool:
                tmdb_tools = []
            tmdb_tools.extend(lib_tools)
        
        if enable_pending_tool:
            pend_tools = self._get_pending_tools_for_openai()
            if not enable_tmdb_tool and not enable_openlibrary_tool and not enable_comicvine_tool and not enable_library_tool:
                tmdb_tools = []
            tmdb_tools.extend(pend_tools)
        
        try:
            # Enforce delay between API calls
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to Ollama API: {model}")
            
            if on_event:
                tools_active = []
                if enable_tmdb_tool: tools_active.append("tmdb")
                if enable_openlibrary_tool: tools_active.append("openlibrary")
                if enable_comicvine_tool: tools_active.append("comicvine")
                if enable_library_tool: tools_active.append("library")
                if enable_pending_tool: tools_active.append("pending")
                on_event({"type": "api_request", "provider": "ollama", "model": model, "tools": tools_active})
            
            # Log full request
            logger.info("=" * 80)
            logger.info("OLLAMA API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Base URL: {base_url}")
            logger.info(f"Model: {model}")
            logger.info(f"TMDB Tool Enabled: {len(tmdb_tools) > 0}")
            logger.debug(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.debug(f"Full Prompt:\n{prompt}")
            if tmdb_tools:
                logger.debug(f"Tools: {json.dumps(tmdb_tools, indent=2)}")
            logger.info("=" * 80)
            
            # Use Ollama's generate endpoint with configurable parameters
            url = f"{base_url}/api/generate"
            
            # Get Ollama parameters from config (with defaults) and ensure they're proper numeric types
            temperature = float(self.config_manager.get('OLLAMA_TEMPERATURE', 0.1))
            num_predict = int(self.config_manager.get('OLLAMA_NUM_PREDICT', 2048))
            top_k = int(self.config_manager.get('OLLAMA_TOP_K', 40))
            top_p = float(self.config_manager.get('OLLAMA_TOP_P', 0.9))
            
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "top_k": top_k,
                    "top_p": top_p
                }
            }
            
            # Add tools if available (Ollama supports function calling in newer versions)
            if tmdb_tools:
                payload["tools"] = tmdb_tools
            
            logger.info(f"Ollama options: temperature={temperature}, num_predict={num_predict}, top_k={top_k}, top_p={top_p}")
            
            req_start = time.time()
            response = requests.post(url, json=payload, timeout=120)
            req_duration = int((time.time() - req_start) * 1000)
            self.last_api_call_time = time.time()
            
            # Log response before raising error
            if response.status_code != 200:
                logger.error(f"Ollama API returned status code: {response.status_code}")
                logger.error(f"Response body: {response.text}")
                try:
                    error_data = response.json()
                    logger.error(f"Error details: {json.dumps(error_data, indent=2)}")
                except:
                    pass
            
            response.raise_for_status()
            
            logger.info(f"Received successful response from Ollama API (status: {response.status_code})")
            
            if on_event:
                on_event({"type": "api_response", "turn": 1, "duration_ms": req_duration})
            
            data = response.json()
            
            # Handle thinking models - check if there's a thinking field
            # For models like deepseek-r1, the response structure includes thinking and content separately
            if 'message' in data and isinstance(data['message'], dict):
                # New format with message object
                message = data['message']
                if 'thinking' in message and message['thinking']:
                    # Model produced thinking - extract actual content
                    text = message.get('content', '')
                    logger.info("Detected thinking model output - extracted content field")
                else:
                    # No thinking, use content normally
                    text = message.get('content', '')
            else:
                # Legacy format - use response field
                text = data.get('response', '')
            
            # Log full response
            logger.info("=" * 80)
            logger.info("OLLAMA API RESPONSE")
            logger.info("=" * 80)
            logger.info(f"Status Code: {response.status_code}")
            logger.debug(f"Full Response:\n{json.dumps(data, indent=2)}")
            if 'message' in data and 'thinking' in data.get('message', {}):
                logger.info(f"Thinking detected (length: {len(data['message']['thinking'])} chars)")
            logger.info("=" * 80)
            
            return self._parse_ai_response(text, "Ollama", on_event)
                
        except requests.exceptions.HTTPError as e:
            logger.error(f"Ollama API HTTP error: {e}, Status code: {response.status_code if 'response' in locals() else 'N/A'}")
            logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
            if on_event:
                on_event({"type": "error", "message": f"HTTP error: {e}"})
            raise
        except requests.exceptions.Timeout:
            logger.error("Ollama API request timed out")
            if on_event:
                on_event({"type": "error", "message": "Request timed out"})
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API connection error: {e}")
            if on_event:
                on_event({"type": "error", "message": f"Connection error: {e}"})
            raise
        except Exception as e:
            logger.error(f"Unexpected error during AI processing: {type(e).__name__}: {e}")
            if on_event:
                on_event({"type": "error", "message": str(e)})
            raise
            raise
