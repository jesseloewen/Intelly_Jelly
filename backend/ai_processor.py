import json
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class AIProcessor:
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def _get_instructions(self) -> str:
        instructions_path = self.config_manager.get('INSTRUCTIONS_FILE_PATH', './instructions.txt')
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
        """Process files using Google AI with optional web search."""
        logger.info(f"Starting AI processing for {len(file_paths)} file(s)")
        logger.debug(f"Files to process: {file_paths}")
        logger.debug(f"Custom prompt: {custom_prompt}, Include default: {include_default}, Include filename: {include_filename}, Web search: {enable_web_search}")
        
        api_key = self.config_manager.get_env('GOOGLE_API_KEY')
        if not api_key:
            logger.error("GOOGLE_API_KEY not found in environment")
            raise ValueError("GOOGLE_API_KEY not found in environment")
        
        model = self.config_manager.get('AI_MODEL', 'gemini-pro')
        logger.info(f"Using AI model: {model}")
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default, include_filename)
        
        if enable_web_search:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.7,
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
                    "temperature": 0.7,
                    "topK": 1,
                    "topP": 1,
                    "maxOutputTokens": 2048,
                }
            }
        
        try:
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

    def get_available_models(self, provider: Optional[str] = None) -> List[str]:
        """Get available Google AI models."""
        logger.info("Fetching available Google AI models")
        try:
            models = self._get_google_models()
            logger.info(f"Successfully fetched {len(models)} available models")
            return models
        except Exception as e:
            logger.error(f"Error fetching Google models: {type(e).__name__}: {e}")
            return []

    def _get_google_models(self) -> List[str]:
        api_key = self.config_manager.get_env('GOOGLE_API_KEY')
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found, cannot fetch models")
            return []
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        logger.debug(f"Fetching models from: {url.split('?')[0]}")
        
        response = requests.get(url)
        response.raise_for_status()
        
        logger.debug(f"Models API response status: {response.status_code}")
        
        data = response.json()
        models = [m['name'].replace('models/', '') for m in data.get('models', [])]
        logger.debug(f"Found {len(models)} models: {models[:5]}..." if len(models) > 5 else f"Found {len(models)} models: {models}")
        return sorted(models)
