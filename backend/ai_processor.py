import json
import requests
from typing import List, Dict, Optional, Tuple
from openai import OpenAI


class AIProcessor:
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def _get_instructions(self) -> str:
        instructions_path = self.config_manager.get('INSTRUCTIONS_FILE_PATH', './instructions.txt')
        try:
            with open(instructions_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Suggest improved file names for the following files. Return JSON array with original_path, suggested_name, and confidence (0-100)."

    def _prepare_batch_prompt(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True) -> str:
        base_instructions = self._get_instructions() if include_default else ""
        
        if custom_prompt:
            prompt = f"{base_instructions}\n\nAdditional instructions: {custom_prompt}\n\n"
        else:
            prompt = f"{base_instructions}\n\n"
        
        prompt += "Files to process:\n"
        for path in file_paths:
            prompt += f"- {path}\n"
        
        return prompt

    def process_batch_openai(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True) -> List[Dict]:
        api_key = self.config_manager.get_env('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        
        model = self.config_manager.get('AI_MODEL', 'gpt-3.5-turbo')
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default)
        
        client = OpenAI(api_key=api_key)
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful file naming assistant. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            if isinstance(result, dict) and 'files' in result:
                return result['files']
            elif isinstance(result, list):
                return result
            else:
                return []
                
        except Exception as e:
            print(f"OpenAI API error: {e}")
            raise

    def process_batch_google(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True) -> List[Dict]:
        api_key = self.config_manager.get_env('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        
        model = self.config_manager.get('AI_MODEL', 'gemini-pro')
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default)
        
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
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            
            text = text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()
            
            result = json.loads(text)
            
            if isinstance(result, dict) and 'files' in result:
                return result['files']
            elif isinstance(result, list):
                return result
            else:
                return []
                
        except Exception as e:
            print(f"Google API error: {e}")
            raise

    def process_batch_ollama(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True) -> List[Dict]:
        ollama_url = self.config_manager.get('OLLAMA_API_URL', 'http://localhost:11434')
        model = self.config_manager.get('AI_MODEL', 'llama3:latest')
        prompt = self._prepare_batch_prompt(file_paths, custom_prompt, include_default)
        
        url = f"{ollama_url}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            
            data = response.json()
            text = data.get('response', '')
            
            result = json.loads(text)
            
            if isinstance(result, dict) and 'files' in result:
                return result['files']
            elif isinstance(result, list):
                return result
            else:
                return []
                
        except Exception as e:
            print(f"Ollama API error: {e}")
            raise

    def process_batch(self, file_paths: List[str], custom_prompt: Optional[str] = None, include_default: bool = True) -> List[Dict]:
        provider = self.config_manager.get('AI_PROVIDER', 'ollama')
        
        if provider == 'openai':
            return self.process_batch_openai(file_paths, custom_prompt, include_default)
        elif provider == 'google':
            return self.process_batch_google(file_paths, custom_prompt, include_default)
        elif provider == 'ollama':
            return self.process_batch_ollama(file_paths, custom_prompt, include_default)
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

    def get_available_models(self, provider: Optional[str] = None) -> List[str]:
        if provider is None:
            provider = self.config_manager.get('AI_PROVIDER', 'ollama')
        
        try:
            if provider == 'openai':
                return self._get_openai_models()
            elif provider == 'google':
                return self._get_google_models()
            elif provider == 'ollama':
                return self._get_ollama_models()
            else:
                return []
        except Exception as e:
            print(f"Error fetching models for {provider}: {e}")
            if provider == 'openai':
                return self._openai_chat_model_candidates()
            return []

    def _openai_chat_model_candidates(self) -> List[str]:
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ]

    def _get_openai_models(self) -> List[str]:
        api_key = self.config_manager.get_env('OPENAI_API_KEY')
        if not api_key:
            return self._openai_chat_model_candidates()
        
        org = self.config_manager.get_env('OPENAI_ORG') or self.config_manager.get_env('OPENAI_ORGANIZATION')
        
        try:
            if org:
                client = OpenAI(api_key=api_key, organization=org)
            else:
                client = OpenAI(api_key=api_key)
            
            models = client.models.list()
            ids = [m.id for m in models.data]
            
            allowed_prefixes = ("gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-4-turbo")
            candidates = sorted({mid for mid in ids if mid.startswith(allowed_prefixes)})
            
            return candidates if candidates else self._openai_chat_model_candidates()
        except Exception as e:
            print(f"OpenAI models.list error: {e}")
            return self._openai_chat_model_candidates()

    def _get_google_models(self) -> List[str]:
        api_key = self.config_manager.get_env('GOOGLE_API_KEY')
        if not api_key:
            return []
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        models = [m['name'].replace('models/', '') for m in data.get('models', [])]
        return sorted(models)

    def _get_ollama_models(self) -> List[str]:
        ollama_url = self.config_manager.get('OLLAMA_API_URL', 'http://localhost:11434')
        url = f"{ollama_url}/api/tags"
        
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        models = [m['name'] for m in data.get('models', [])]
        return sorted(models)
