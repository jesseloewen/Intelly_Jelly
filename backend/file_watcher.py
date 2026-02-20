import os
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable, Optional
from pathlib import Path


class DownloadingFolderHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str, str], None], base_path: str):
        self.callback = callback
        self.base_path = base_path

    def update_base_path(self, new_base_path: str):
        self.base_path = new_base_path

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            relative_path = os.path.relpath(file_path, self.base_path)
            self.callback(file_path, relative_path)

    def on_moved(self, event):
        if not event.is_directory:
            file_path = event.dest_path
            relative_path = os.path.relpath(file_path, self.base_path)
            self.callback(file_path, relative_path)


class CompletedFolderHandler(FileSystemEventHandler):
    """Handler for completed folder - moves files directly to library without AI processing."""
    def __init__(self, callback: Callable[[str, str], None], base_path: str):
        self.callback = callback
        self.base_path = base_path

    def update_base_path(self, new_base_path: str):
        self.base_path = new_base_path

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            relative_path = os.path.relpath(file_path, self.base_path)
            self.callback(file_path, relative_path)

    def on_moved(self, event):
        if not event.is_directory:
            file_path = event.dest_path
            relative_path = os.path.relpath(file_path, self.base_path)
            self.callback(file_path, relative_path)


class FileWatcher:
    def __init__(self, path: str, handler: FileSystemEventHandler):
        self.path = path
        self.handler = handler
        self.observer: Optional[Observer] = None
        self._running = False

    def start(self):
        if self._running:
            return
        
        os.makedirs(self.path, exist_ok=True)
        
        self.observer = Observer()
        self.observer.schedule(self.handler, self.path, recursive=True)
        self.observer.start()
        self._running = True
        print(f"Started watching: {self.path} (recursive)")

    def stop(self):
        if self.observer and self._running:
            self.observer.stop()
            self.observer.join()
            self._running = False
            print(f"Stopped watching: {self.path}")

    def restart(self, new_path: str):
        self.stop()
        self.path = new_path
        self.start()


class DebouncedProcessor:
    def __init__(self, debounce_seconds: int, process_callback: Callable):
        self.debounce_seconds = debounce_seconds
        self.process_callback = process_callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def trigger(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            
            self._timer = threading.Timer(self.debounce_seconds, self._execute)
            self._timer.start()

    def _execute(self):
        try:
            self.process_callback()
        except Exception as e:
            print(f"Error in debounced processor: {e}")

    def stop(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def update_debounce_time(self, new_seconds: int):
        self.debounce_seconds = new_seconds
