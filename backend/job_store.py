import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class JobStatus(Enum):
    QUEUED_FOR_AI = "Queued for AI"
    PROCESSING_AI = "Processing AI"
    PENDING_COMPLETION = "Pending Completion"
    COMPLETED = "Completed"
    FAILED = "Failed"
    MANUAL_EDIT = "Manual Edit"


class Job:
    def __init__(self, original_path: str, relative_path: str):
        self.job_id = str(uuid.uuid4())
        self.original_path = original_path
        self.relative_path = relative_path
        self.status = JobStatus.QUEUED_FOR_AI
        self.ai_determined_name: Optional[str] = None
        self.new_path: Optional[str] = None
        self.confidence: Optional[int] = None
        self.error_message: Optional[str] = None
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.custom_prompt: Optional[str] = None
        self.priority: bool = False
        self.include_instructions: bool = True
        self.include_filename: bool = True
        self.enable_web_search: bool = False
        self.enable_tmdb_tool: bool = False
        self.retry_count: int = 0
        self.max_retries: int = 3
        self._missing_since: Optional[float] = None
        self.completed_file_path: Optional[str] = None
        self.group_id: Optional[str] = None  # Links files with same base name
        self.is_group_primary: bool = False  # First file in a group is primary
        self.source_folder: Optional[str] = None  # Track which folder file came from (downloading, uploads, or completed)

    def to_dict(self) -> dict:
        return {
            'job_id': self.job_id,
            'original_path': self.original_path,
            'relative_path': self.relative_path,
            'status': self.status.value,
            'ai_determined_name': self.ai_determined_name,
            'new_path': self.new_path,
            'confidence': self.confidence,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'priority': self.priority,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries
        }

    def update_status(self, status: JobStatus, **kwargs):
        self.status = status
        self.updated_at = datetime.now()
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


class JobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()

    def add_job(self, original_path: str, relative_path: str) -> Job:
        with self._lock:
            job = Job(original_path, relative_path)
            self._jobs[job.job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_by_path(self, path: str) -> Optional[Job]:
        with self._lock:
            for job in self._jobs.values():
                if job.original_path == path or job.relative_path == path:
                    return job
            return None

    def get_jobs_by_status(self, status: JobStatus) -> List[Job]:
        with self._lock:
            return [job for job in self._jobs.values() if job.status == status]

    def get_all_jobs(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())

    def update_job(self, job_id: str, status: JobStatus, **kwargs) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update_status(status, **kwargs)
                return True
            return False

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    def get_priority_jobs(self) -> List[Job]:
        with self._lock:
            return [job for job in self._jobs.values() 
                   if job.priority and job.status == JobStatus.QUEUED_FOR_AI]
    
    def get_failed_jobs_for_retry(self) -> List[Job]:
        """Get failed jobs that haven't exceeded max retries."""
        with self._lock:
            return [job for job in self._jobs.values() 
                   if job.status == JobStatus.FAILED and job.retry_count < job.max_retries]

    def clear_completed_jobs(self, days: int = 7):
        with self._lock:
            cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
            to_delete = [
                job_id for job_id, job in self._jobs.items()
                if job.status == JobStatus.COMPLETED 
                and job.updated_at.timestamp() < cutoff
            ]
            for job_id in to_delete:
                del self._jobs[job_id]

    def get_jobs_by_group(self, group_id: str) -> List[Job]:
        """Get all jobs that belong to the same group."""
        with self._lock:
            return [job for job in self._jobs.values() if job.group_id == group_id]
    
    def find_job_by_base_name(self, base_name: str) -> Optional[Job]:
        """Find existing job with same base name (without extension)."""
        with self._lock:
            import os
            for job in self._jobs.values():
                job_base_name = os.path.splitext(os.path.basename(job.relative_path))[0]
                if job_base_name == base_name:
                    return job
            return None
            return len(to_delete)
