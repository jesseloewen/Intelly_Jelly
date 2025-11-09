"""
File Organizer
Handles renaming and moving files to the library based on job data.
"""

import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from backend.config_manager import get_config
from backend.job_store import get_job_store, JobStatus


class FileOrganizer:
    """Organizes completed files into the library."""
    
    def __init__(self):
        self.config = get_config()
        self.job_store = get_job_store()
        self._running = False
        self._thread = None
    
    def start(self):
        """Start the file organizer thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._organizer_loop, daemon=True)
        self._thread.start()
        print("File organizer started")
    
    def stop(self):
        """Stop the file organizer thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _organizer_loop(self):
        """Main loop that checks for files ready to organize."""
        while self._running:
            try:
                # Get all jobs pending completion
                pending_jobs = self.job_store.get_jobs_by_status(JobStatus.PENDING_COMPLETION)
                
                for job in pending_jobs:
                    self._organize_file(job)
                
                # Sleep between checks
                time.sleep(2)
            
            except Exception as e:
                print(f"Error in organizer loop: {e}")
                time.sleep(5)
    
    def _organize_file(self, job: dict) -> bool:
        """Organize a single file based on its job data."""
        try:
            original_path = Path(job['original_path'])
            
            # Check if file exists
            if not original_path.exists():
                print(f"File not found: {original_path}")
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.FAILED,
                    'error_message': 'File not found'
                })
                return False
            
            # Get new name and subfolder
            new_name = job.get('new_name')
            subfolder = job.get('subfolder', '')
            
            if not new_name:
                print(f"No new name for job {job['job_id']}")
                self.job_store.update_job(job['job_id'], {
                    'status': JobStatus.FAILED,
                    'error_message': 'No new name specified'
                })
                return False
            
            # Build destination path
            library_path = Path(self.config.get('LIBRARY_PATH', './test_library'))
            
            if subfolder:
                destination_dir = library_path / subfolder
            else:
                destination_dir = library_path
            
            # Ensure destination directory exists
            destination_dir.mkdir(parents=True, exist_ok=True)
            
            # Build full destination path
            destination_path = destination_dir / new_name
            
            # Handle duplicate filenames
            if destination_path.exists():
                stem = destination_path.stem
                suffix = destination_path.suffix
                counter = 1
                while destination_path.exists():
                    destination_path = destination_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            # Move the file
            print(f"Moving: {original_path.name} -> {destination_path}")
            shutil.move(str(original_path), str(destination_path))
            
            # Update job as completed
            self.job_store.update_job(job['job_id'], {
                'status': JobStatus.COMPLETED,
                'original_path': str(destination_path)
            })
            
            print(f"Successfully organized: {destination_path}")
            return True
        
        except Exception as e:
            print(f"Error organizing file: {e}")
            self.job_store.update_job(job['job_id'], {
                'status': JobStatus.FAILED,
                'error_message': str(e)
            })
            return False
    
    def organize_now(self, job_id: str) -> bool:
        """Immediately organize a specific job."""
        job = self.job_store.get_job(job_id)
        if not job:
            return False
        
        if job['status'] != JobStatus.PENDING_COMPLETION:
            # Update status first
            self.job_store.update_job(job_id, {
                'status': JobStatus.PENDING_COMPLETION
            })
            job['status'] = JobStatus.PENDING_COMPLETION
        
        return self._organize_file(job)


# Global organizer instance
_organizer_instance = None
_organizer_lock = threading.Lock()


def get_file_organizer() -> FileOrganizer:
    """Get the global file organizer instance."""
    global _organizer_instance
    if _organizer_instance is None:
        with _organizer_lock:
            if _organizer_instance is None:
                _organizer_instance = FileOrganizer()
    return _organizer_instance
