import json
import logging
import os
import requests
import time
from typing import List, Dict, Optional
from openai import OpenAI
from backend.tmdb_api import TMDBClient, format_tool_response

logger = logging.getLogger(__name__)


class AIProcessor:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.last_api_call_time = 0
        self.openai_client = None
        self.tmdb_client = None
        
        # Hardcoded model lists
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
        
        # Ollama models are fetched dynamically from the server
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
    
    def _execute_tmdb_function(self, function_name: str, args: Dict) -> str:
        """Execute a TMDB function call and return formatted response."""
        client = self._get_tmdb_client()
        if not client:
            return "TMDB tool is not available"
        
        try:
            if function_name == "search_movie":
                result = client.search_movie(args.get("movie_name", ""))
                return format_tool_response(result, "movie")
            
            elif function_name == "search_tv_show":
                result = client.search_tv_show(args.get("tv_show_name", ""))
                return format_tool_response(result, "tv")
            
            elif function_name == "get_tv_episode_info":
                result = client.get_tv_episode_info(
                    args.get("tv_show_name", ""),
                    args.get("season_number", 1),
                    args.get("episode_number")
                )
                return format_tool_response(result, "episode")
            
            else:
                return f"Unknown function: {function_name}"
        
        except Exception as e:
            logger.error(f"Error executing TMDB function {function_name}: {e}")
            return f"Error: {str(e)}"
    
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

    def process_single(self, file_path: str, custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False) -> Optional[Dict]:
        """Process a single file using configured AI with optional web search and TMDB tool."""
        logger.info(f"Starting AI processing for file: {file_path}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}")
        
        # Process as single-item batch and return first result
        results = self.process_batch([file_path], custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool)
        return results[0] if results else None
    
    def process_batch(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False) -> List[Dict]:
        """Process files using configured AI provider with optional web search and TMDB tool."""
        logger.info(f"Starting AI processing for {len(file_paths)} file(s)")
        logger.debug(f"Files to process: {file_paths}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}")
        
        # Override enable_tmdb_tool based on actual config state (if not explicitly disabled)
        if enable_tmdb_tool:
            tmdb_enabled_in_config = self.config_manager.get('ENABLE_TMDB_TOOL', False)
            if not tmdb_enabled_in_config:
                logger.warning("TMDB tool requested but not enabled in config, disabling for this request")
                enable_tmdb_tool = False
        
        provider = self.config_manager.get('AI_PROVIDER', 'google')
        logger.info(f"Using AI provider: {provider}")
        
        if provider == 'openai':
            return self._process_batch_openai(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool)
        elif provider == 'ollama':
            return self._process_batch_ollama(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool)
        else:
            return self._process_batch_google(file_paths, custom_prompt, include_default, include_filename, enable_web_search, enable_tmdb_tool)
    
    def _process_batch_google(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False) -> List[Dict]:
        """Process files using Google AI with optional web search and TMDB tool."""
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
        
        if tools:
            payload["tools"] = tools
        
        try:
            # Enforce delay between API calls to avoid rate limiting
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to Google AI API: {model}")
            logger.debug(f"API URL: {url.split('?')[0]}")  # Log URL without API key
            logger.debug(f"Payload config: temperature={payload['generationConfig']['temperature']}, maxTokens={payload['generationConfig']['maxOutputTokens']}")
            
            # Log full request payload (without API key)
            logger.info("=" * 80)
            logger.info("GOOGLE AI API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.info(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.info(f"Full Prompt:\n{prompt}")
            logger.info(f"Generation Config: {json.dumps(payload['generationConfig'], indent=2)}")
            if 'tools' in payload:
                logger.info(f"Tools: {json.dumps(payload['tools'], indent=2)}")
            logger.info("=" * 80)
            
            # Handle multi-turn conversation for function calling
            conversation_history = payload["contents"].copy()
            max_turns = 5  # Prevent infinite loops
            
            for turn in range(max_turns):
                response = requests.post(url, json=payload)
                self.last_api_call_time = time.time()  # Record time of API call
                response.raise_for_status()
                
                logger.info(f"Received successful response from Google AI API (status: {response.status_code})")
                
                # Log full response
                logger.info("=" * 80)
                logger.info(f"GOOGLE AI API RESPONSE (Turn {turn + 1})")
                logger.info("=" * 80)
                logger.info(f"Status Code: {response.status_code}")
                logger.info(f"Full Response:\n{json.dumps(response.json(), indent=2)}")
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
                        
                        logger.info(f"Executing function: {func_name} with args: {func_args}")
                        result = self._execute_tmdb_function(func_name, func_args)
                        
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
                
                text = text.strip()
                if text.startswith('```json'):
                    text = text[7:]
                if text.startswith('```'):
                    text = text[3:]
                if text.endswith('```'):
                    text = text[:-3]
                text = text.strip()
                
                logger.debug("Parsing AI response as JSON")
                result = json.loads(text)
                
                if isinstance(result, dict) and 'files' in result:
                    logger.info(f"AI processing completed successfully: {len(result['files'])} results returned")
                    return result['files']
                elif isinstance(result, list):
                    logger.info(f"AI processing completed successfully: {len(result)} results returned")
                    return result
                else:
                    logger.warning("AI response did not contain expected format, returning empty list")
                    return []
            
            # Max turns reached
            logger.warning(f"Maximum conversation turns ({max_turns}) reached without final answer")
            return []
                
        except requests.exceptions.HTTPError as e:
            logger.error(f"Google API HTTP error: {e}, Status code: {response.status_code if 'response' in locals() else 'N/A'}")
            logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Raw response text: {text if 'text' in locals() else 'N/A'}")
            raise
        except KeyError as e:
            logger.error(f"Unexpected response structure from Google API: {e}")
            logger.error(f"Response data: {data if 'data' in locals() else 'N/A'}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during AI processing: {type(e).__name__}: {e}")
            raise

    def _process_batch_openai(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False) -> List[Dict]:
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
            
            # Log full request
            logger.info("=" * 80)
            logger.info("OPENAI API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.info(f"TMDB Tool Enabled: {enable_tmdb_tool}")
            logger.info(f"API: {'chat.completions' if use_chat_api else 'responses'}")
            logger.info(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.info(f"Full Prompt:\n{prompt}")
            if tools:
                logger.info(f"Tools: {json.dumps(tools, indent=2)}")
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
                max_turns = 5
                turn = 0
                
                while turn < max_turns:
                    turn += 1
                    logger.info(f"OpenAI conversation turn {turn}/{max_turns}")
                    
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
                    
                    self.last_api_call_time = time.time()
                    message = response.choices[0].message
                    messages.append(message)
                    
                    # Check if AI made tool calls
                    if message.tool_calls:
                        logger.info(f"AI requested {len(message.tool_calls)} tool call(s)")
                        
                        # Execute each tool call
                        for tool_call in message.tool_calls:
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)
                            
                            logger.info(f"Executing function: {function_name} with args: {function_args}")
                            
                            # Execute TMDB function
                            function_result = self._execute_tmdb_function(function_name, function_args)
                            
                            # Add function result to messages
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(function_result)
                            })
                            
                            logger.info(f"Function {function_name} returned: {function_result}")
                        
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
                response = self.openai_client.responses.create(
                    model=model,
                    input=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty
                )
                
                self.last_api_call_time = time.time()
                logger.info(f"Received successful response from OpenAI Responses API")
                
                # Extract the text using output_text
                text = response.output_text
            
            logger.info("=" * 80)
            logger.info("OPENAI API RESPONSE")
            logger.info("=" * 80)
            logger.info(f"Response length: {len(text)} characters")
            logger.info(f"Full Response:\n{text}")
            logger.info("=" * 80)
            
            logger.debug(f"Raw AI response length: {len(text)} characters")
            
            # Parse response
            text = text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()
            
            logger.debug("Parsing AI response as JSON")
            result = json.loads(text)
            
            if isinstance(result, dict) and 'files' in result:
                logger.info(f"AI processing completed successfully: {len(result['files'])} results returned")
                return result['files']
            elif isinstance(result, list):
                logger.info(f"AI processing completed successfully: {len(result)} results returned")
                return result
            else:
                logger.warning("AI response did not contain expected format, returning empty list")
                return []
                
        except Exception as e:
            logger.error(f"OpenAI API error: {type(e).__name__}: {e}")
            raise

    def get_available_models(self, provider: Optional[str] = None) -> List[str]:
        """Get available models for the specified provider."""
        if not provider:
            provider = self.config_manager.get('AI_PROVIDER', 'google')
        
        logger.info(f"Fetching available models for provider: {provider}")
        
        if provider == 'openai':
            return self.OPENAI_MODELS
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
    
    def _process_batch_ollama(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False) -> List[Dict]:
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
            tmdb_tools = self._get_tmdb_tools_for_openai()  # Ollama uses OpenAI-compatible format
        else:
            tmdb_tools = []
        
        try:
            # Enforce delay between API calls
            delay_seconds = self.config_manager.get('AI_CALL_DELAY_SECONDS', 2)
            time_since_last_call = time.time() - self.last_api_call_time
            
            if time_since_last_call < delay_seconds:
                wait_time = delay_seconds - time_since_last_call
                logger.info(f"Rate limit protection: waiting {wait_time:.2f} seconds before API call")
                time.sleep(wait_time)
            
            logger.info(f"Sending request to Ollama API: {model}")
            
            # Log full request
            logger.info("=" * 80)
            logger.info("OLLAMA API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Base URL: {base_url}")
            logger.info(f"Model: {model}")
            logger.info(f"TMDB Tool Enabled: {len(tmdb_tools) > 0}")
            logger.info(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.info(f"Full Prompt:\n{prompt}")
            if tmdb_tools:
                logger.info(f"Tools: {json.dumps(tmdb_tools, indent=2)}")
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
            
            response = requests.post(url, json=payload, timeout=120)
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
            logger.info(f"Full Response:\n{json.dumps(data, indent=2)}")
            if 'message' in data and 'thinking' in data.get('message', {}):
                logger.info(f"Thinking detected (length: {len(data['message']['thinking'])} chars)")
            logger.info("=" * 80)
            
            logger.debug(f"Raw AI response length: {len(text)} characters")
            
            # Parse response
            text = text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()
            
            logger.debug("Parsing AI response as JSON")
            result = json.loads(text)
            
            if isinstance(result, dict) and 'files' in result:
                logger.info(f"AI processing completed successfully: {len(result['files'])} results returned")
                return result['files']
            elif isinstance(result, list):
                logger.info(f"AI processing completed successfully: {len(result)} results returned")
                return result
            else:
                logger.warning("AI response did not contain expected format, returning empty list")
                return []
                
        except requests.exceptions.HTTPError as e:
            logger.error(f"Ollama API HTTP error: {e}, Status code: {response.status_code if 'response' in locals() else 'N/A'}")
            logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Raw response text: {text if 'text' in locals() else 'N/A'}")
            raise
        except requests.exceptions.Timeout:
            logger.error("Ollama API request timed out")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API connection error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during AI processing: {type(e).__name__}: {e}")
            raise
