import json
import os
import threading
from typing import Any, Dict, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv


class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def on_modified(self, event):
        if event.src_path.endswith('config.json'):
            self.config_manager.reload_config()


class ConfigManager:
    def __init__(self, config_path: str = 'config.json', env_path: str = '.env'):
        self.config_path = config_path
        self.env_path = env_path
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._observers = []
        self._change_callbacks = []
        
        load_dotenv(self.env_path)
        
        self.reload_config()
        self._start_watching()

    def reload_config(self):
        with self._lock:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    new_config = json.load(f)
                    old_config = self._config.copy()
                    self._config = new_config
                    
                    if old_config != new_config:
                        self._notify_changes(old_config, new_config)
                        
            except FileNotFoundError:
                print(f"Config file {self.config_path} not found. Using defaults.")
                self._config = self._get_default_config()
            except json.JSONDecodeError as e:
                print(f"Error parsing config file: {e}")
            except UnicodeDecodeError as e:
                print(f"Unicode decode error reading config file: {e}. Using defaults.")
                self._config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "DOWNLOADING_PATH": "./test_folders/downloading",
            "COMPLETED_PATH": "./test_folders/completed",
            "LIBRARY_PATH": "./test_folders/library",
            "INSTRUCTIONS_FILE_PATH": "./instructions.md",
            "AI_PROVIDER": "google",
            "AI_MODEL": "gemini-2.0-flash-exp",
            "DRY_RUN_MODE": False,
            "ENABLE_WEB_SEARCH": True
        }

    def _start_watching(self):
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        event_handler = ConfigChangeHandler(self)
        observer = Observer()
        observer.schedule(event_handler, config_dir, recursive=False)
        observer.start()
        self._observers.append(observer)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return self._config.copy()

    def set(self, key: str, value: Any):
        with self._lock:
            self._config[key] = value

    def save(self):
        with self._lock:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, indent=2)
                return True
            except Exception as e:
                print(f"Error saving config: {e}")
                return False

    def update_config(self, updates: Dict[str, Any]) -> bool:
        with self._lock:
            self._config.update(updates)
            return self.save()

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(key, default)

    def register_change_callback(self, callback):
        self._change_callbacks.append(callback)

    def _notify_changes(self, old_config: Dict, new_config: Dict):
        for callback in self._change_callbacks:
            try:
                callback(old_config, new_config)
            except Exception as e:
                print(f"Error in config change callback: {e}")

    def stop(self):
        for observer in self._observers:
            observer.stop()
            observer.join()
