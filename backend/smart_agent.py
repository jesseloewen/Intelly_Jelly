import json
import logging
import os
import re
import time
import threading
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from backend.job_store import JobStore, JobStatus
from backend.tmdb_api import TMDBClient, format_tool_response
from backend.openlibrary_api import OpenLibraryClient, format_openlibrary_response
from backend.comicvine_api import ComicVineClient, format_comicvine_response

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_CONVERSATION_TURNS = 10

AGENT_SYSTEM_PROMPT = """You are an expert media file organizer agent. Process batches of files by assigning each a proper destination path.

CRITICAL WORKFLOW (2-3 steps):
1. Call plan_lookups ONCE to declare ALL metadata you need (shows, books, movies, library searches, queue searches). This is the KEY to efficiency — declare everything upfront.
2. The system will return ALL metadata results combined. Do NOT call individual metadata tools.
3. Call set_names ONCE with ALL files' names. Then call finish_group().

OPTIONAL: Before plan_lookups, call search_queue to find related files in the queue that should be processed together.

CRITICAL RULES:
- Use plan_lookups for ALL metadata needs. Never call individual search_movie/search_tv_show/etc tools.
- Call set_names with ALL files at once (array of names), not one at a time.
- For TV shows: declare the show + season in plan_lookups, get all episode info back, name every episode.
- For books: declare the book in plan_lookups, get author + year back, name all chapter files.
- Multi-format files (.pdf+.epub same book) go in the same folder with their respective extensions.
- Subtitles (.srt, .sub) go in the same folder as their video with matching base name.
- If a file cannot be named, still include it in set_names with lower confidence.
- NEVER output JSON directly. Use the tools.
"""


class SmartAgent:
    def __init__(self, config_manager, job_store: JobStore, library_browser=None,
                 ai_processor=None):
        self.config_manager = config_manager
        self.job_store = job_store
        self.library_browser = library_browser
        self.ai_processor = ai_processor
        
        self.tmdb_client: Optional[TMDBClient] = None
        self.openlibrary_client: Optional[OpenLibraryClient] = None
        self.comicvine_client: Optional[ComicVineClient] = None
        self.openai_client: Optional[OpenAI] = None
        self.openrouter_client: Optional[OpenAI] = None
        self.last_api_call_time = 0
        
        self._current_batch_id: Optional[str] = None
        self._named_count = 0
        self._batch_total = 0

    def _get_tmdb_client(self) -> Optional[TMDBClient]:
        if not self.config_manager.get('ENABLE_TMDB_TOOL', False):
            return None
        api_key = self.config_manager.get('TMDB_API_KEY', '')
        if not api_key:
            return None
        if not self.tmdb_client:
            self.tmdb_client = TMDBClient(api_key)
        return self.tmdb_client

    def _get_openlibrary_client(self) -> Optional[OpenLibraryClient]:
        if not self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False):
            return None
        if not self.openlibrary_client:
            self.openlibrary_client = OpenLibraryClient()
        return self.openlibrary_client

    def _get_comicvine_client(self) -> Optional[ComicVineClient]:
        if not self.config_manager.get('ENABLE_COMICVINE_TOOL', False):
            return None
        api_key = self.config_manager.get('COMICVINE_API_KEY', '')
        if not api_key:
            return None
        if not self.comicvine_client:
            self.comicvine_client = ComicVineClient(api_key)
        return self.comicvine_client

    def _get_plan_lookups_tool(self) -> Dict:
        has_tmdb = bool(self._get_tmdb_client())
        has_ol = bool(self._get_openlibrary_client())
        has_cv = bool(self._get_comicvine_client())
        
        return {
            "type": "function",
            "function": {
                "name": "plan_lookups",
                "description": "Declare ALL metadata lookups needed for the entire batch. The system will execute ALL lookups in parallel and return combined results. This is the PRIMARY tool for gathering metadata — use it instead of individual search tools. Declare everything upfront to minimize API calls.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tmdb": {
                            "type": "array",
                            "description": "TMDB lookups needed. Each entry: {type, name, season?}. Types: 'movie', 'tv_show', 'tv_episodes' (requires season number). For tv_episodes, omit episode_number to get all episodes.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["movie", "tv_show", "tv_episodes"]},
                                    "name": {"type": "string", "description": "Movie or TV show name to search"},
                                    "season": {"type": "integer", "description": "Season number (required for tv_episodes)"}
                                },
                                "required": ["type", "name"]
                            }
                        },
                        "openlibrary": {
                            "type": "array",
                            "description": "Open Library lookups. Types: 'book', 'audiobook', 'author'.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["book", "audiobook", "author"]},
                                    "name": {"type": "string"}
                                },
                                "required": ["type", "name"]
                            }
                        },
                        "comicvine": {
                            "type": "array",
                            "description": "Comic Vine lookups. Types: 'volume', 'issue'.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["volume", "issue"]},
                                    "name": {"type": "string"}
                                },
                                "required": ["type", "name"]
                            }
                        },
                        "library_searches": {
                            "type": "array",
                            "description": "Library searches to perform. Each: {query, category?}. Category: 'movies','tv','music','books','audiobooks','comics','software','other'.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "category": {"type": "string"}
                                },
                                "required": ["query"]
                            }
                        },
                        "queue_searches": {
                            "type": "array",
                            "description": "Queue searches to find related files. Each: {query, max_results?}.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "max_results": {"type": "integer"}
                                },
                                "required": ["query"]
                            }
                        }
                    },
                    "required": []
                }
            }
        }

    def _get_agent_tools_openai(self) -> List[Dict]:
        tools = [
            self._get_plan_lookups_tool(),
            {
                "type": "function",
                "function": {
                    "name": "set_names",
                    "description": "Set the final destination names for ALL files in the batch at once. Pass an array of {original_path, suggested_name, confidence} objects. The suggested_name must follow the exact naming conventions (e.g., 'TV Shows/Show (Year)/Season XX/Show (Year) - SXXEYY - Episode Name.ext'). Call this ONCE with all files, then call finish_group().",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "names": {
                                "type": "array",
                                "description": "Array of name assignments for every file in the batch",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "original_path": {"type": "string", "description": "Exact relative_path from the input"},
                                        "suggested_name": {"type": "string", "description": "Full destination path including category, folders, and filename"},
                                        "confidence": {"type": "integer", "description": "Confidence score 0-100"}
                                    },
                                    "required": ["original_path", "suggested_name", "confidence"]
                                }
                            }
                        },
                        "required": ["names"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "finish_group",
                    "description": "Mark the batch as complete. Call ONCE after set_names has been called for all files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "note": {"type": "string", "description": "Optional summary"}
                        },
                        "required": []
                    }
                }
            },
        ]
        
        if self.job_store:
            tools.append({
                "type": "function",
                "function": {
                    "name": "search_queue",
                    "description": "Search the processing queue for related files (other episodes, subtitle files, multi-format copies). Use this BEFORE plan_lookups to discover additional files to process.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search term or empty string to list all"},
                            "max_results": {"type": "integer", "description": "Max results (default 30)"}
                        },
                        "required": ["query"]
                    }
                }
            })
        
        return tools

    def _execute_plan_lookups(self, args: Dict) -> str:
        """Execute ALL metadata lookups declared in plan_lookups in parallel.
        
        Returns a single combined JSON result with all lookup results.
        """
        tasks = []
        
        def safe_lookup(name, fn):
            try:
                return {name: fn()}
            except Exception as e:
                logger.error(f"plan_lookups error in {name}: {e}")
                return {name: f"Error: {str(e)}"}
        
        tmdb_lookups = args.get("tmdb", [])
        ol_lookups = args.get("openlibrary", [])
        cv_lookups = args.get("comicvine", [])
        lib_searches = args.get("library_searches", [])
        queue_searches = args.get("queue_searches", [])
        
        # Build TMDB tasks
        tmdb_client = self._get_tmdb_client()
        for item in tmdb_lookups:
            lookup_type = item.get("type", "")
            name = item.get("name", "")
            season = item.get("season")
            
            if lookup_type == "movie" and tmdb_client:
                tasks.append(lambda n=name, c=tmdb_client: safe_lookup(f"tmdb:movie:{n}",
                    lambda: format_tool_response(c.search_movie(n), "movie")))
            elif lookup_type == "tv_show" and tmdb_client:
                tasks.append(lambda n=name, c=tmdb_client: safe_lookup(f"tmdb:tv_show:{n}",
                    lambda: format_tool_response(c.search_tv_show(n), "tv")))
            elif lookup_type == "tv_episodes" and tmdb_client:
                s = season or 1
                tasks.append(lambda n=name, sn=s, c=tmdb_client: safe_lookup(f"tmdb:tv_episodes:{n}_s{sn}",
                    lambda: format_tool_response(c.get_tv_episode_info(n, sn, None), "episode")))
        
        # Build Open Library tasks
        ol_client = self._get_openlibrary_client()
        for item in ol_lookups:
            lookup_type = item.get("type", "")
            name = item.get("name", "")
            if not ol_client:
                continue
            if lookup_type == "book":
                tasks.append(lambda n=name, c=ol_client: safe_lookup(f"openlibrary:book:{n}",
                    lambda: format_openlibrary_response(c.search_book(n), "book")))
            elif lookup_type == "audiobook":
                tasks.append(lambda n=name, c=ol_client: safe_lookup(f"openlibrary:audiobook:{n}",
                    lambda: format_openlibrary_response(c.search_audiobook(n), "audiobook")))
            elif lookup_type == "author":
                tasks.append(lambda n=name, c=ol_client: safe_lookup(f"openlibrary:author:{n}",
                    lambda: format_openlibrary_response(c.search_author(n), "author")))
        
        # Build Comic Vine tasks
        cv_client = self._get_comicvine_client()
        for item in cv_lookups:
            lookup_type = item.get("type", "")
            name = item.get("name", "")
            if not cv_client:
                continue
            if lookup_type == "volume":
                tasks.append(lambda n=name, c=cv_client: safe_lookup(f"comicvine:volume:{n}",
                    lambda: format_comicvine_response(c.search_volume(n), "volume")))
            elif lookup_type == "issue":
                tasks.append(lambda n=name, c=cv_client: safe_lookup(f"comicvine:issue:{n}",
                    lambda: format_comicvine_response(c.search_issue(n), "issue")))
        
        # Build library search tasks
        for item in lib_searches:
            query = item.get("query", "")
            category = item.get("category")
            if self.library_browser and os.path.exists(self.library_browser.library_path):
                tasks.append(lambda q=query, c=category: safe_lookup(f"library:{q}",
                    lambda: json.dumps(self.library_browser.search_library(q, category=c, max_results=20), indent=2)))
        
        # Build queue search tasks
        for item in queue_searches:
            query = item.get("query", "")
            max_results = item.get("max_results", 30)
            if self.job_store:
                tasks.append(lambda q=query, m=max_results: safe_lookup(f"queue:{q}",
                    lambda: json.dumps(self.job_store.search_queue(q, max_results=m), indent=2)))
        
        if not tasks:
            return json.dumps({"result": "No lookups requested"})
        
        # Execute all tasks in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(task) for task in tasks]
            for future in as_completed(futures):
                try:
                    results.update(future.result())
                except Exception as e:
                    logger.error(f"plan_lookups future error: {e}")
        
        summary = {
            "total_lookups": len(tasks),
            "results": results
        }
        return json.dumps(summary, indent=2)

    def _execute_tool(self, function_name: str, args: Dict) -> str:
        """Execute a tool call locally and return the result string."""
        try:
            if function_name == "plan_lookups":
                return self._execute_plan_lookups(args)

            elif function_name == "search_queue":
                if not self.job_store:
                    return "Queue search not available"
                results = self.job_store.search_queue(
                    args.get("query", ""),
                    max_results=args.get("max_results", 30)
                )
                if not results:
                    return "No matching queued files found."
                return json.dumps(results, indent=2)

            elif function_name == "set_names":
                if not self.job_store:
                    return json.dumps({"error": "Job store not available"})
                names = args.get("names", [])
                if not names:
                    return json.dumps({"status": "error", "error": "No names provided"})
                
                named = []
                not_found = []
                for entry in names:
                    original_path = entry.get("original_path", "")
                    suggested_name = entry.get("suggested_name", "")
                    confidence = entry.get("confidence", 0)
                    
                    job = self.job_store.get_job_by_path(original_path)
                    if not job:
                        for j in self.job_store.get_jobs_by_batch(self._current_batch_id or ""):
                            if j.relative_path == original_path:
                                job = j
                                break
                    
                    if not job:
                        not_found.append(original_path)
                        continue
                    
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.AGENT_NAMED,
                        suggested_name=suggested_name,
                        confidence=confidence,
                    )
                    named.append(original_path)
                    logger.info(f"Agent set_names: {original_path} -> {suggested_name} (confidence: {confidence})")
                
                self._named_count = len(named)
                for i, path in enumerate(named):
                    job = self.job_store.get_job_by_path(path)
                    if job:
                        self.job_store.update_job_batch_status(
                            job.job_id,
                            position=i + 1,
                            total=self._batch_total,
                            message=f"Named: {os.path.basename(path)}"
                        )
                
                return json.dumps({
                    "status": "ok",
                    "named_count": len(named),
                    "not_found": not_found,
                    "total": self._batch_total
                })

            elif function_name == "finish_group":
                return "FINISH_GROUP_REQUESTED"

            else:
                return f"Unknown function: {function_name}"

        except Exception as e:
            logger.error(f"Error executing {function_name}: {e}")
            return f"Error: {str(e)}"

    def _enforce_rate_limit(self):
        delay = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
        elapsed = time.time() - self.last_api_call_time
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _get_instructions(self) -> str:
        custom_path = './instruction_prompt_custom.md'
        base_path = './instruction_prompt.md'
        instructions_path = custom_path if os.path.exists(custom_path) else base_path
        try:
            with open(instructions_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "Organize media files into the proper library structure."
        except UnicodeDecodeError:
            return "Organize media files into the proper library structure."

    def process_batch(self, file_paths: List[str], custom_prompt: Optional[str] = None,
                      on_event: Optional[Callable] = None) -> Dict:
        """Run the smart agent on a batch of files.
        
        Returns:
            Dict with keys: 'status' (success/partial/failed), 'named' (count of successfully named files),
            'failed' (count of failed files), 'note' (summary message), 'batch_id'.
        """
        self._named_count = 0
        self._batch_total = len(file_paths)
        self._current_batch_id = str(__import__('uuid').uuid4())
        
        batch_jobs = []
        for fp in file_paths:
            job = self.job_store.get_job_by_path(fp)
            if job:
                job.batch_id = self._current_batch_id
                batch_jobs.append(job)
                
        if not batch_jobs:
            logger.warning("No valid jobs found for agent batch")
            return {"status": "failed", "named": 0, "failed": 0, "note": "No valid jobs", "batch_id": self._current_batch_id}
        
        self._batch_total = len(batch_jobs)
        for j in batch_jobs:
            self.job_store.update_job(j.job_id, JobStatus.PROCESSING_AI)
        
        provider = self.config_manager.get('AI_PROVIDER', 'openrouter')
        
        logger.info(f"Smart Agent starting batch {self._current_batch_id}: {self._batch_total} files via {provider}")
        
        if on_event:
            on_event({"type": "agent_batch_started", "batch_id": self._current_batch_id,
                      "total": self._batch_total, "files": file_paths[:5]})
            on_event({"type": "job_started", "job_id": batch_jobs[0].job_id,
                      "file": f"Agent batch: {self._batch_total} files"})
        
        try:
            if provider in ("openai", "openrouter"):
                result = self._run_openai_agent(batch_jobs, file_paths, custom_prompt, on_event)
            elif provider == "google":
                result = self._run_google_agent(batch_jobs, file_paths, custom_prompt, on_event)
            elif provider == "ollama":
                result = self._run_ollama_agent(batch_jobs, file_paths, custom_prompt, on_event)
            else:
                result = self._run_openai_agent(batch_jobs, file_paths, custom_prompt, on_event)
            
            self._finalize_batch(batch_jobs, result, on_event)
            return result
            
        except Exception as e:
            logger.error(f"Agent batch failed: {e}", exc_info=True)
            for j in batch_jobs:
                if j.status not in (JobStatus.AGENT_NAMED, JobStatus.PENDING_COMPLETION):
                    self.job_store.update_job(j.job_id, JobStatus.FAILED,
                                             error_message=str(e))
            if on_event:
                on_event({"type": "agent_batch_error", "batch_id": self._current_batch_id, "error": str(e)})
            return {"status": "failed", "named": self._named_count, "failed": self._batch_total - self._named_count,
                    "note": str(e), "batch_id": self._current_batch_id}

    def _run_openai_agent(self, batch_jobs, file_paths, custom_prompt, on_event):
        api_key = self.config_manager.get('OPENAI_API_KEY' if self.config_manager.get('AI_PROVIDER') == 'openai' else 'OPENROUTER_API_KEY', '')
        if not api_key:
            raise ValueError("API key not configured")
        
        if self.config_manager.get('AI_PROVIDER') == 'openai':
            if not self.openai_client:
                self.openai_client = OpenAI(api_key=api_key)
            client = self.openai_client
        else:
            if not self.openrouter_client:
                self.openrouter_client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
            client = self.openrouter_client
        
        model = self.config_manager.get('AI_MODEL', 'deepseek/deepseek-chat')
        tools = self._get_agent_tools_openai()
        
        instructions = self._get_instructions()
        prompt = self._build_agent_prompt(file_paths, instructions, custom_prompt)
        
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        if on_event:
            on_event({"type": "api_request", "provider": "openrouter", "model": model,
                      "tools": [t["function"]["name"] for t in tools]})
            on_event({"type": "thinking", "message": f"Analyzing {len(file_paths)} files..."})
        
        temp = float(self.config_manager.get('OPENROUTER_TEMPERATURE', 0.1))
        max_tok = int(self.config_manager.get('OPENROUTER_MAX_TOKENS', 4096))
        top_p = float(self.config_manager.get('OPENROUTER_TOP_P', 1))
        
        return self._agent_conversation_loop(client, model, messages, tools, temp, max_tok, top_p, on_event)

    def _run_google_agent(self, batch_jobs, file_paths, custom_prompt, on_event):
        api_key = self.config_manager.get('GOOGLE_API_KEY', '')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not configured")
        
        model = self.config_manager.get('AI_MODEL', 'gemini-2.5-flash')
        instructions = self._get_instructions()
        prompt = self._build_agent_prompt(file_paths, instructions, custom_prompt)
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        google_tools = self._build_google_tools()
        
        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": AGENT_SYSTEM_PROMPT + "\n\n" + prompt}]
            }],
            "generationConfig": {
                "temperature": float(self.config_manager.get('GOOGLE_TEMPERATURE', 0.1)),
                "topK": int(self.config_manager.get('GOOGLE_TOP_K', 1)),
                "topP": float(self.config_manager.get('GOOGLE_TOP_P', 1)),
                "maxOutputTokens": int(self.config_manager.get('GOOGLE_MAX_TOKENS', 2048)),
            }
        }
        if google_tools:
            payload["tools"] = google_tools
        
        if on_event:
            on_event({"type": "api_request", "provider": "google", "model": model, "tools": ["agent_tools"]})
        
        return self._google_conversation_loop(url, payload, on_event)

    def _run_ollama_agent(self, batch_jobs, file_paths, custom_prompt, on_event):
        base_url = self.config_manager.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        model = self.config_manager.get('AI_MODEL', 'deepseek-r1:1.5b')
        instructions = self._get_instructions()
        prompt = self._build_agent_prompt(file_paths, instructions, custom_prompt)
        
        full_prompt = AGENT_SYSTEM_PROMPT + "\n\n" + prompt
        
        if on_event:
            on_event({"type": "api_request", "provider": "ollama", "model": model, "tools": []})
        
        url = f"{base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": float(self.config_manager.get('OLLAMA_TEMPERATURE', 0.1)),
                "num_predict": int(self.config_manager.get('OLLAMA_NUM_PREDICT', 2048)),
                "top_k": int(self.config_manager.get('OLLAMA_TOP_K', 40)),
                "top_p": float(self.config_manager.get('OLLAMA_TOP_P', 0.9)),
            }
        }
        
        self._enforce_rate_limit()
        import requests
        resp = requests.post(url, json=payload, timeout=120)
        self.last_api_call_time = time.time()
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
        
        return {"status": "success", "note": "Ollama agent completed", "raw_response": text[:500]}

    def _build_agent_prompt(self, file_paths, instructions, custom_prompt):
        prompt = f"{instructions}\n\n"
        prompt += "FILES TO PROCESS:\n"
        for fp in file_paths:
            prompt += f"- {fp}\n"
        prompt += f"\nTotal: {len(file_paths)} files.\n\n"
        prompt += ("WORKFLOW: 1. Call plan_lookups with ALL metadata you need (shows, books, movies, library/queue searches). "
                   "2. The system returns ALL results combined. 3. Call set_names with ALL files' names. "
                   "4. Call finish_group(). Do NOT use individual search tools — use plan_lookups for everything.")
        if custom_prompt:
            prompt += f"\n\nAdditional instructions: {custom_prompt}"
        return prompt

    def _build_google_tools(self):
        tools = [
            {
                "function_declarations": [
                    {
                        "name": "plan_lookups",
                        "description": "Declare ALL metadata lookups needed. System executes them in parallel.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "tmdb": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "name": {"type": "string"}, "season": {"type": "integer"}}, "required": ["type", "name"]}},
                                "openlibrary": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "name": {"type": "string"}}, "required": ["type", "name"]}},
                                "comicvine": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "name": {"type": "string"}}, "required": ["type", "name"]}},
                                "library_searches": {"type": "array", "items": {"type": "object", "properties": {"query": {"type": "string"}, "category": {"type": "string"}}, "required": ["query"]}},
                                "queue_searches": {"type": "array", "items": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
                            },
                            "required": []
                        }
                    },
                    {
                        "name": "set_names",
                        "description": "Set names for ALL files at once. Pass array of {original_path, suggested_name, confidence}.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "names": {
                                    "type": "array",
                                    "items": {"type": "object", "properties": {"original_path": {"type": "string"}, "suggested_name": {"type": "string"}, "confidence": {"type": "integer"}}, "required": ["original_path", "suggested_name", "confidence"]}
                                }
                            },
                            "required": ["names"]
                        }
                    },
                    {
                        "name": "finish_group",
                        "description": "Mark batch complete after all files named.",
                        "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": []}
                    },
                ]
            }
        ]
        if self.job_store:
            tools.append({
                "function_declarations": [{
                    "name": "search_queue",
                    "description": "Search queued files for related items.",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}
                }]
            })
        return tools

    def _agent_conversation_loop(self, client, model, messages, tools, temp, max_tok, top_p, on_event):
        turn = 0
        finish_requested = False
        
        while turn < MAX_CONVERSATION_TURNS:
            turn += 1
            self._enforce_rate_limit()
            
            req_start = time.time()
            kwargs = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": temp,
                "max_tokens": max_tok,
                "top_p": top_p,
            }
            response = client.chat.completions.create(**kwargs)
            req_duration = int((time.time() - req_start) * 1000)
            self.last_api_call_time = time.time()
            
            message = response.choices[0].message
            messages.append(message)
            
            if on_event:
                on_event({"type": "api_response", "turn": turn, "duration_ms": req_duration})
            
            if message.tool_calls:
                logger.info(f"Agent turn {turn}: {len(message.tool_calls)} tool call(s)")
                
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)
                    
                    if on_event:
                        on_event({"type": "tool_started", "tool": func_name,
                                  "args": json.dumps(func_args)[:200]})
                    
                    result = self._execute_tool(func_name, func_args)
                    
                    if on_event:
                        on_event({"type": "tool_completed", "tool": func_name})
                    
                    if result == "FINISH_GROUP_REQUESTED":
                        finish_requested = True
                        note = func_args.get("note", "")
                        logger.info(f"Agent requested finish_group: {note}")
                        if on_event:
                            on_event({"type": "thinking", "message": f"Batch complete: {note}"})
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                
                if finish_requested:
                    break
                
                if on_event and self._named_count > 0:
                    on_event({"type": "thinking",
                              "message": f"Named {self._named_count}/{self._batch_total} files"})
                continue
            
            if message.content:
                text = message.content.strip()
                logger.info(f"Agent final text response (turn {turn}): {text[:200]}")
                break
        
        return {
            "status": "success" if self._named_count > 0 else "failed",
            "named": self._named_count,
            "note": "Agent completed" if finish_requested else "Agent ended without finish_group"
        }

    def _google_conversation_loop(self, url, payload, on_event):
        import requests
        conversation = payload["contents"].copy()
        max_turns = MAX_CONVERSATION_TURNS
        
        for turn in range(max_turns):
            self._enforce_rate_limit()
            req_start = time.time()
            resp = requests.post(url, json=payload)
            req_duration = int((time.time() - req_start) * 1000)
            self.last_api_call_time = time.time()
            resp.raise_for_status()
            
            if on_event:
                on_event({"type": "api_response", "turn": turn + 1, "duration_ms": req_duration})
            
            data = resp.json()
            candidate = data['candidates'][0]
            parts = candidate['content']['parts']
            
            function_calls = [p for p in parts if 'functionCall' in p]
            
            if function_calls:
                conversation.append(candidate['content'])
                func_responses = []
                
                for fc in function_calls:
                    func_name = fc['functionCall']['name']
                    func_args = fc['functionCall'].get('args', {})
                    
                    if on_event:
                        on_event({"type": "tool_started", "tool": func_name,
                                  "args": json.dumps(func_args)[:200]})
                    
                    result = self._execute_tool(func_name, func_args)
                    
                    if on_event:
                        on_event({"type": "tool_completed", "tool": func_name})
                    
                    if result == "FINISH_GROUP_REQUESTED":
                        return {"status": "success", "named": self._named_count,
                                "note": "Agent completed via finish_group"}
                    
                    func_responses.append({
                        "functionResponse": {"name": func_name, "response": {"result": result}}
                    })
                
                conversation.append({"parts": func_responses})
                payload["contents"] = conversation
                
                delay = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
                time.sleep(delay)
                continue
            
            text_parts = [p.get('text', '') for p in parts if 'text' in p]
            if text_parts:
                text = ''.join(text_parts)
                logger.info(f"Google agent text response: {text[:200]}")
            break
        
        return {"status": "success" if self._named_count > 0 else "failed",
                "named": self._named_count, "note": "Google agent completed"}

    def _finalize_batch(self, batch_jobs, result, on_event):
        """Transition successfully named jobs to PENDING_COMPLETION."""
        success_count = 0
        fail_count = 0
        
        for job in batch_jobs:
            current = self.job_store.get_job(job.job_id)
            if not current:
                continue
            if current.status == JobStatus.AGENT_NAMED:
                self.job_store.update_job(current.job_id, JobStatus.PENDING_COMPLETION)
                success_count += 1
                logger.info(f"Agent finalized: {current.relative_path} -> {current.suggested_name}")
            elif current.status not in (JobStatus.PENDING_COMPLETION, JobStatus.COMPLETED):
                self.job_store.update_job(current.job_id, JobStatus.FAILED,
                                         error_message="Agent did not name this file")
                fail_count += 1
        
        logger.info(f"Agent batch {self._current_batch_id} finalized: {success_count} success, {fail_count} failed")
        
        result["named"] = success_count
        result["failed"] = fail_count
        result["status"] = "success" if success_count > 0 else "failed"
        if success_count > 0 and fail_count > 0:
            result["status"] = "partial"
        result["batch_id"] = self._current_batch_id
        
        if on_event:
            first_job = batch_jobs[0] if batch_jobs else None
            on_event({"type": "agent_batch_done", "batch_id": self._current_batch_id,
                      "status": result["status"], "named": success_count, "failed": fail_count})
            if first_job:
                on_event({"type": "job_done", "job_id": first_job.job_id,
                          "status": "pending_completion", "confidence": 85,
                          "name": f"Agent batch: {success_count} files named"})