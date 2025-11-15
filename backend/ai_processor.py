import json
import logging
import os
import requests
import time
from typing import List, Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class AIProcessor:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.last_api_call_time = 0
        self.openai_client = None
        
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

    def process_single(self, file_path: str, custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False) -> Optional[Dict]:
        """Process a single file using Google AI with optional web search."""
        logger.info(f"Starting AI processing for file: {file_path}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}")
        
        # Process as single-item batch and return first result
        results = self.process_batch([file_path], custom_prompt, include_default, include_filename, enable_web_search)
        return results[0] if results else None
    
    def process_batch(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False) -> List[Dict]:
        """Process files using configured AI provider with optional web search."""
        logger.info(f"Starting AI processing for {len(file_paths)} file(s)")
        logger.debug(f"Files to process: {file_paths}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}")
        
        provider = self.config_manager.get('AI_PROVIDER', 'google')
        logger.info(f"Using AI provider: {provider}")
        
        if provider == 'openai':
            return self._process_batch_openai(file_paths, custom_prompt, include_default, include_filename, enable_web_search)
        else:
            return self._process_batch_google(file_paths, custom_prompt, include_default, include_filename, enable_web_search)
    
    def _process_batch_google(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False) -> List[Dict]:
        """Process files using Google AI with optional web search."""
        api_key = self.config_manager.get('GOOGLE_API_KEY', '')
        if not api_key:
            logger.error("GOOGLE_API_KEY not found in configuration")
            raise ValueError("GOOGLE_API_KEY not set. Please configure it in Settings.")
        
        model = self.config_manager.get('AI_MODEL', 'gemini-2.5-flash')
        logger.info(f"Using AI model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        if enable_web_search:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 1,
                    "topP": 1,
                    "maxOutputTokens": 2048,
                },
                "tools": [{
                    "google_search": {}
                }]
            }
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 1,
                    "topP": 1,
                    "maxOutputTokens": 2048,
                }
            }
        
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
            
            response = requests.post(url, json=payload)
            self.last_api_call_time = time.time()  # Record time of API call
            response.raise_for_status()
            
            logger.info(f"Received successful response from Google AI API (status: {response.status_code})")
            
            # Log full response
            logger.info("=" * 80)
            logger.info("GOOGLE AI API RESPONSE")
            logger.info("=" * 80)
            logger.info(f"Status Code: {response.status_code}")
            logger.info(f"Full Response:\n{json.dumps(response.json(), indent=2)}")
            logger.info("=" * 80)
            
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            
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

    def _process_batch_openai(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True, include_filename: bool = True, enable_web_search: bool = False) -> List[Dict]:
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
            
            # Log full request
            logger.info("=" * 80)
            logger.info("OPENAI API REQUEST")
            logger.info("=" * 80)
            logger.info(f"Model: {model}")
            logger.info(f"Web Search Enabled: {enable_web_search}")
            logger.info(f"Prompt (first 500 chars): {prompt[:500]}...")
            logger.info(f"Full Prompt:\n{prompt}")
            logger.info("=" * 80)
            
            # Use responses.create API with tools parameter
            response = self.openai_client.responses.create(
                model=model,
                input=prompt,
                tools=[{"type": "web_search"}] if enable_web_search else []
            )
            
            self.last_api_call_time = time.time()
            
            logger.info(f"Received successful response from OpenAI API")
            
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
        else:
            return self.GOOGLE_MODELS
