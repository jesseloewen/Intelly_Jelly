"""
Configuration Manager
Handles loading and reloading of config.json and .env files.
Provides thread-safe access to configuration values.
"""

import json
import os
import threading
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv


class ConfigManager:
    """Manages application configuration with live reloading support."""
    
    def __init__(self, config_path: str = "config.json", env_path: str = ".env"):
        self.config_path = Path(config_path)
        self.env_path = Path(env_path)
        self._config: Dict[str, Any] = {}
        self._env: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._last_modified = 0.0
        self._callbacks = []
        
        # Load initial configuration
        self.reload()
    
    def reload(self) -> bool:
        """
        Reload configuration from files.
        Returns True if configuration changed, False otherwise.
        """
        with self._lock:
            changed = False
            
            # Check if config file was modified
            if self.config_path.exists():
                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != self._last_modified:
                    try:
                        with open(self.config_path, 'r') as f:
                            new_config = json.load(f)
                        
                        if new_config != self._config:
                            self._config = new_config
                            changed = True
                        
                        self._last_modified = current_mtime
                    except Exception as e:
                        print(f"Error loading config: {e}")
            
            # Load environment variables (these don't change during runtime)
            if self.env_path.exists() and not self._env:
                load_dotenv(self.env_path)
                self._env = {
                    'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', ''),
                    'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY', ''),
                }
            
            # Notify callbacks if configuration changed
            if changed:
                self._notify_callbacks()
            
            return changed
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        with self._lock:
            return self._config.get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
        with self._lock:
            return self._config.copy()
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save to file."""
        with self._lock:
            self._config[key] = value
            self._save()
    
    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple configuration values and save to file."""
        with self._lock:
            self._config.update(updates)
            self._save()
    
    def _save(self) -> None:
        """Save configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self._config, f, indent=2)
            self._last_modified = self.config_path.stat().st_mtime
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for a specific provider."""
        with self._lock:
            key_map = {
                'openai': 'OPENAI_API_KEY',
                'google': 'GOOGLE_API_KEY',
            }
            env_key = key_map.get(provider.lower())
            if env_key:
                return self._env.get(env_key)
            return None
    
    def register_callback(self, callback):
        """Register a callback to be called when configuration changes."""
        with self._lock:
            self._callbacks.append(callback)
    
    def _notify_callbacks(self):
        """Notify all registered callbacks of configuration change."""
        for callback in self._callbacks:
            try:
                callback(self._config.copy())
            except Exception as e:
                print(f"Error in config callback: {e}")


# Global configuration instance
_config_instance = None
_config_lock = threading.Lock()


def get_config() -> ConfigManager:
    """Get the global configuration manager instance."""
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = ConfigManager()
    return _config_instance
