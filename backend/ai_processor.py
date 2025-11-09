"""
AI Processor
Handles AI-based file naming using multiple providers (OpenAI, Google, Ollama).
Supports both batch processing and priority queue processing.
"""

import json
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import queue

from backend.config_manager import get_config
from backend.job_store import get_job_store, JobStatus


class AIProvider:
    """Base class for AI providers."""
    
    def process_batch(self, filenames: List[str], instructions: str, custom_prompt: str = None) -> Dict[str, Any]:
        """Process a batch of filenames and return suggested names."""
        raise NotImplementedError
    
    def get_available_models(self) -> List[str]:
        """Get list of available models for this provider."""
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key)
            except Exception as e:
                print(f"Error initializing OpenAI client: {e}")
    
    def process_batch(self, filenames: List[str], instructions: str, custom_prompt: str = None) -> Dict[str, Any]:
        """Process batch using OpenAI."""
        if not self.client:
            return {"error": "OpenAI client not initialized"}
        
        try:
            config = get_config()
            model = config.get('AI_MODEL', 'gpt-3.5-turbo')
            
            # Build the prompt
            prompt = f"{instructions}\n\nFiles to process:\n"
            for filename in filenames:
                prompt += f"- {filename}\n"
            
            if custom_prompt:
                prompt += f"\n{custom_prompt}"
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a file naming assistant. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            result = response.choices[0].message.content
            return json.loads(result)
        
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return {"error": str(e)}
    
    def get_available_models(self) -> List[str]:
        """Get available OpenAI models."""
        if not self.client:
            return []
        
        try:
            models = self.client.models.list()
            # Filter to GPT models only
            gpt_models = [m.id for m in models.data if 'gpt' in m.id.lower()]
            return sorted(gpt_models)
        except Exception as e:
            print(f"Error fetching OpenAI models: {e}")
            return ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo-preview']


class GoogleProvider(AIProvider):
    """Google Gemini provider."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = None
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self.genai = genai
            except Exception as e:
                print(f"Error initializing Google AI: {e}")
    
    def process_batch(self, filenames: List[str], instructions: str, custom_prompt: str = None) -> Dict[str, Any]:
        """Process batch using Google Gemini."""
        if not self.genai:
            return {"error": "Google AI not initialized"}
        
        try:
            config = get_config()
            model_name = config.get('AI_MODEL', 'gemini-pro')
            model = self.genai.GenerativeModel(model_name)
            
            # Build the prompt
            prompt = f"{instructions}\n\nFiles to process:\n"
            for filename in filenames:
                prompt += f"- {filename}\n"
            
            if custom_prompt:
                prompt += f"\n{custom_prompt}"
            
            # Call Google API
            response = model.generate_content(prompt)
            
            # Try to extract JSON from the response
            text = response.text
            # Find JSON in the response
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = text[start:end]
                return json.loads(json_str)
            else:
                return {"error": "No JSON found in response"}
        
        except Exception as e:
            print(f"Google AI error: {e}")
            return {"error": str(e)}
    
    def get_available_models(self) -> List[str]:
        """Get available Google models."""
        if not self.genai:
            return []
        
        try:
            models = self.genai.list_models()
            model_names = [m.name.split('/')[-1] for m in models if 'generateContent' in m.supported_generation_methods]
            return sorted(model_names)
        except Exception as e:
            print(f"Error fetching Google models: {e}")
            return ['gemini-pro', 'gemini-pro-vision']


class OllamaProvider(AIProvider):
    """Ollama local LLM provider."""
    
    def __init__(self):
        pass
    
    def process_batch(self, filenames: List[str], instructions: str, custom_prompt: str = None) -> Dict[str, Any]:
        """Process batch using Ollama."""
        try:
            import requests
            
            config = get_config()
            api_url = config.get('OLLAMA_API_URL', 'http://localhost:11434')
            model = config.get('AI_MODEL', 'llama3:latest')
            
            # Build the prompt
            prompt = f"{instructions}\n\nFiles to process:\n"
            for filename in filenames:
                prompt += f"- {filename}\n"
            
            if custom_prompt:
                prompt += f"\n{custom_prompt}"
            
            prompt += "\n\nRespond with ONLY valid JSON, no other text."
            
            # Call Ollama API
            response = requests.post(
                f"{api_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '')
                
                # Try to parse JSON from response
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    # Try to extract JSON if wrapped in markdown or other text
                    start = response_text.find('{')
                    end = response_text.rfind('}') + 1
                    if start >= 0 and end > start:
                        json_str = response_text[start:end]
                        return json.loads(json_str)
                    return {"error": "Invalid JSON response from Ollama"}
            else:
                return {"error": f"Ollama API error: {response.status_code}"}
        
        except Exception as e:
            print(f"Ollama error: {e}")
            return {"error": str(e)}
    
    def get_available_models(self) -> List[str]:
        """Get available Ollama models."""
        try:
            import requests
            
            config = get_config()
            api_url = config.get('OLLAMA_API_URL', 'http://localhost:11434')
            
            response = requests.get(f"{api_url}/api/tags", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                models = [m['name'] for m in data.get('models', [])]
                return sorted(models)
            else:
                return []
        
        except Exception as e:
            print(f"Error fetching Ollama models: {e}")
            return []


class AIProcessor:
    """Manages AI processing with batch and priority queues."""
    
    def __init__(self):
        self.config = get_config()
        self.job_store = get_job_store()
        
        self.priority_queue = queue.Queue()
        self._running = False
        self._batch_thread = None
        self._priority_thread = None
        
        # Register for config changes
        self.config.register_callback(self._on_config_changed)
    
    def start(self):
        """Start the AI processing threads."""
        if self._running:
            return
        
        self._running = True
        
        # Start batch processing thread
        self._batch_thread = threading.Thread(target=self._batch_processor, daemon=True)
        self._batch_thread.start()
        
        # Start priority processing thread
        self._priority_thread = threading.Thread(target=self._priority_processor, daemon=True)
        self._priority_thread.start()
        
        print("AI processor started")
    
    def stop(self):
        """Stop the AI processing threads."""
        self._running = False
        if self._batch_thread:
            self._batch_thread.join(timeout=5)
        if self._priority_thread:
            self._priority_thread.join(timeout=5)
    
    def _get_provider(self) -> Optional[AIProvider]:
        """Get the current AI provider based on configuration."""
        provider_name = self.config.get('AI_PROVIDER', 'ollama').lower()
        
        if provider_name == 'openai':
            api_key = self.config.get_api_key('openai')
            if not api_key:
                print("Warning: OpenAI API key not found")
                return None
            return OpenAIProvider(api_key)
        
        elif provider_name == 'google':
            api_key = self.config.get_api_key('google')
            if not api_key:
                print("Warning: Google API key not found")
                return None
            return GoogleProvider(api_key)
        
        elif provider_name == 'ollama':
            return OllamaProvider()
        
        else:
            print(f"Unknown AI provider: {provider_name}")
            return None
    
    def _load_instructions(self) -> str:
        """Load instructions from file."""
        instructions_path = self.config.get('INSTRUCTIONS_FILE_PATH', 'instructions.txt')
        try:
            with open(instructions_path, 'r') as f:
                return f.read()
        except Exception as e:
            print(f"Error loading instructions: {e}")
            return "Please suggest organized names for these files."
    
    def _batch_processor(self):
        """Background thread that processes queued jobs in batches."""
        while self._running:
            try:
                # Check for queued jobs
                queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
                
                if queued_jobs:
                    batch_size = self.config.get('AI_BATCH_SIZE', 10)
                    batch = queued_jobs[:batch_size]
                    
                    print(f"Processing batch of {len(batch)} jobs")
                    self._process_batch(batch)
                
                # Sleep between checks
                time.sleep(2)
            
            except Exception as e:
                print(f"Error in batch processor: {e}")
                time.sleep(5)
    
    def _priority_processor(self):
        """Background thread that processes priority queue jobs immediately."""
        while self._running:
            try:
                # Wait for priority job (blocking with timeout)
                try:
                    job_id = self.priority_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                print(f"Processing priority job: {job_id}")
                
                job = self.job_store.get_job(job_id)
                if job:
                    self._process_batch([job], use_custom_prompt=True)
                
                self.priority_queue.task_done()
            
            except Exception as e:
                print(f"Error in priority processor: {e}")
                time.sleep(1)
    
    def _process_batch(self, jobs: List[Dict[str, Any]], use_custom_prompt: bool = False):
        """Process a batch of jobs with AI."""
        if not jobs:
            return
        
        # Get AI provider
        provider = self._get_provider()
        if not provider:
            # Mark jobs as failed
            for job in jobs:
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.FAILED,
                    'error_message': 'AI provider not available'
                })
            return
        
        # Check dry run mode
        dry_run = self.config.get('DRY_RUN_MODE', False)
        
        # Update jobs to PROCESSING_AI
        for job in jobs:
            self.job_store.update_job(job['job_id'], {
                'status': JobStatus.PROCESSING_AI
            })
        
        # Extract filenames
        filenames = [job['original_filename'] for job in jobs]
        
        # Load instructions
        instructions = self._load_instructions()
        
        # Get custom prompt if applicable
        custom_prompt = None
        if use_custom_prompt and len(jobs) == 1:
            custom_prompt = jobs[0].get('custom_prompt')
        
        # Process with AI
        if dry_run:
            # Simulate AI response in dry run mode
            result = self._generate_dry_run_response(filenames)
        else:
            result = provider.process_batch(filenames, instructions, custom_prompt)
        
        # Handle errors
        if 'error' in result:
            for job in jobs:
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.FAILED,
                    'error_message': result['error']
                })
            return
        
        # Update jobs with AI results
        files_data = result.get('files', [])
        
        for job in jobs:
            # Find matching result
            matching = None
            for file_data in files_data:
                if file_data.get('original') == job['original_filename']:
                    matching = file_data
                    break
            
            if matching:
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.PENDING_COMPLETION,
                    'new_name': matching.get('new_name'),
                    'subfolder': matching.get('subfolder'),
                    'ai_response': json.dumps(matching)
                })
                print(f"Job {job['job_id']}: {job['original_filename']} -> {matching.get('new_name')}")
            else:
                # No matching result, mark as failed
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.FAILED,
                    'error_message': 'No AI result for this file'
                })
    
    def _generate_dry_run_response(self, filenames: List[str]) -> Dict[str, Any]:
        """Generate a dummy response for dry run mode."""
        files = []
        for filename in filenames:
            name = Path(filename).stem
            ext = Path(filename).suffix
            files.append({
                "original": filename,
                "new_name": f"Organized - {name}{ext}",
                "subfolder": "Organized Files"
            })
        return {"files": files}
    
    def add_priority_job(self, job_id: str):
        """Add a job to the priority queue for immediate processing."""
        self.priority_queue.put(job_id)
    
    def get_available_models(self) -> List[str]:
        """Get available models for the current provider."""
        provider = self._get_provider()
        if provider:
            return provider.get_available_models()
        return []
    
    def _on_config_changed(self, new_config: dict):
        """Handle configuration changes."""
        print("AI processor detected configuration change")


# Global AI processor instance
_processor_instance = None
_processor_lock = threading.Lock()


def get_ai_processor() -> AIProcessor:
    """Get the global AI processor instance."""
    global _processor_instance
    if _processor_instance is None:
        with _processor_lock:
            if _processor_instance is None:
                _processor_instance = AIProcessor()
    return _processor_instance
