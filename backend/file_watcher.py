"""
File Watcher
Monitors directories for new files and manages debouncing logic.
"""

import threading
import time
from pathlib import Path
from typing import Callable, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from backend.config_manager import get_config
from backend.job_store import get_job_store, JobStatus


class DownloadingWatcher(FileSystemEventHandler):
    """Watches the downloading directory for new files."""
    
    def __init__(self, on_files_ready: Callable):
        super().__init__()
        self.on_files_ready = on_files_ready
        self.pending_files: Set[str] = set()
        self.lock = threading.Lock()
        self.timer = None
        self.debounce_seconds = 5
    
    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        # Ignore temporary files
        if event.src_path.endswith(('.tmp', '.part', '.crdownload')):
            return
        
        with self.lock:
            self.pending_files.add(event.src_path)
            self._reset_timer()
    
    def _reset_timer(self):
        """Reset the debounce timer."""
        if self.timer:
            self.timer.cancel()
        
        config = get_config()
        self.debounce_seconds = config.get('DEBOUNCE_SECONDS', 5)
        
        self.timer = threading.Timer(self.debounce_seconds, self._timer_expired)
        self.timer.daemon = True
        self.timer.start()
    
    def _timer_expired(self):
        """Called when debounce timer expires."""
        with self.lock:
            if self.pending_files:
                files = list(self.pending_files)
                self.pending_files.clear()
                self.on_files_ready(files)
    
    def update_debounce(self, seconds: int):
        """Update debounce time (called when config changes)."""
        with self.lock:
            self.debounce_seconds = seconds


class CompletedWatcher(FileSystemEventHandler):
    """Watches the completed directory for files ready to organize."""
    
    def __init__(self, on_file_completed: Callable):
        super().__init__()
        self.on_file_completed = on_file_completed
    
    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        # Ignore temporary files
        if event.src_path.endswith(('.tmp', '.part', '.crdownload')):
            return
        
        # Small delay to ensure file is fully written
        time.sleep(0.5)
        self.on_file_completed(event.src_path)


class FileWatcherManager:
    """Manages file watchers for downloading and completed directories."""
    
    def __init__(self):
        self.config = get_config()
        self.job_store = get_job_store()
        
        self.downloading_observer = None
        self.completed_observer = None
        self.downloading_handler = None
        self.completed_handler = None
        
        self._running = False
        self._lock = threading.Lock()
        
        # Register for configuration changes
        self.config.register_callback(self._on_config_changed)
    
    def start(self):
        """Start watching directories."""
        with self._lock:
            if self._running:
                return
            
            self._running = True
            self._start_watchers()
    
    def stop(self):
        """Stop watching directories."""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            self._stop_watchers()
    
    def _start_watchers(self):
        """Initialize and start the file watchers."""
        downloading_path = self.config.get('DOWNLOADING_PATH')
        completed_path = self.config.get('COMPLETED_PATH')
        
        # Ensure directories exist
        Path(downloading_path).mkdir(parents=True, exist_ok=True)
        Path(completed_path).mkdir(parents=True, exist_ok=True)
        
        # Start downloading watcher
        self.downloading_handler = DownloadingWatcher(self._on_files_ready)
        self.downloading_observer = Observer()
        self.downloading_observer.schedule(
            self.downloading_handler,
            downloading_path,
            recursive=False
        )
        self.downloading_observer.start()
        print(f"Watching downloading directory: {downloading_path}")
        
        # Start completed watcher
        self.completed_handler = CompletedWatcher(self._on_file_completed)
        self.completed_observer = Observer()
        self.completed_observer.schedule(
            self.completed_handler,
            completed_path,
            recursive=False
        )
        self.completed_observer.start()
        print(f"Watching completed directory: {completed_path}")
    
    def _stop_watchers(self):
        """Stop the file watchers."""
        if self.downloading_observer:
            self.downloading_observer.stop()
            self.downloading_observer.join(timeout=5)
            self.downloading_observer = None
        
        if self.completed_observer:
            self.completed_observer.stop()
            self.completed_observer.join(timeout=5)
            self.completed_observer = None
    
    def _on_files_ready(self, file_paths: list):
        """
        Called when debounce timer expires and files are ready for AI processing.
        Creates jobs for each file.
        """
        print(f"Debounce timer expired. Processing {len(file_paths)} files.")
        
        for file_path in file_paths:
            # Verify file still exists
            if not Path(file_path).exists():
                continue
            
            # Create job with QUEUED_FOR_AI status
            job_id = self.job_store.create_job(
                original_path=file_path,
                status=JobStatus.QUEUED_FOR_AI
            )
            print(f"Created job {job_id} for file: {Path(file_path).name}")
    
    def _on_file_completed(self, file_path: str):
        """
        Called when a file appears in the completed directory.
        Triggers the file organization process.
        """
        filename = Path(file_path).name
        print(f"File completed: {filename}")
        
        # Find the corresponding job
        job = self.job_store.get_job_by_filename(
            filename,
            status=JobStatus.PENDING_COMPLETION
        )
        
        if job:
            # Update job with actual completed path
            self.job_store.update_job(job['job_id'], {
                'original_path': file_path
            })
            print(f"Found matching job {job['job_id']} for completed file")
        else:
            print(f"Warning: No pending job found for {filename}")
            # Create a new job anyway, in case it was added manually
            self.job_store.create_job(
                original_path=file_path,
                status=JobStatus.PENDING_COMPLETION
            )
    
    def _on_config_changed(self, new_config: dict):
        """Handle configuration changes."""
        print("Configuration changed, restarting watchers...")
        
        # Update debounce time if handler exists
        if self.downloading_handler:
            debounce = new_config.get('DEBOUNCE_SECONDS', 5)
            self.downloading_handler.update_debounce(debounce)
        
        # Restart watchers if paths changed
        with self._lock:
            if self._running:
                self._stop_watchers()
                time.sleep(0.5)
                self._start_watchers()


# Global watcher instance
_watcher_instance = None
_watcher_lock = threading.Lock()


def get_watcher_manager() -> FileWatcherManager:
    """Get the global file watcher manager instance."""
    global _watcher_instance
    if _watcher_instance is None:
        with _watcher_lock:
            if _watcher_instance is None:
                _watcher_instance = FileWatcherManager()
    return _watcher_instance
