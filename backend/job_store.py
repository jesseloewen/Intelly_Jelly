import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)

PENDING_JOBS_FILE = 'pending_jobs.json'


class JobStatus(Enum):
    QUEUED_FOR_AI = "Queued for AI"
    PROCESSING_AI = "Processing AI"
    AGENT_NAMED = "Agent Named"
    PENDING_COMPLETION = "Pending Completion"
    COMPLETED = "Completed"
    FAILED = "Failed"
    MANUAL_EDIT = "Manual Edit"


BATCH_PROCESSABLE_STATUSES = {JobStatus.QUEUED_FOR_AI, JobStatus.AGENT_NAMED, JobStatus.PENDING_COMPLETION}

TV_EPISODE_PATTERN = r'[Ss](\d{1,4})[Ee](\d{1,4})'
MEDIA_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v'}
SUBTITLE_EXTENSIONS = {'.srt', '.sub', '.ass', '.ssa', '.vtt', '.idx'}
BOOK_EXTENSIONS = {'.epub', '.mobi', '.pdf', '.azw3', '.azw'}
AUDIOBOOK_EXTENSIONS = {'.m4b', '.m4a'}
COMIC_EXTENSIONS = {'.cbz', '.cbr', '.cbt'}


class Job:
    def __init__(self, original_path: str, relative_path: str):
        self.job_id = str(uuid.uuid4())
        self.original_path = original_path
        self.relative_path = relative_path
        self.status = JobStatus.QUEUED_FOR_AI
        self.suggested_name: Optional[str] = None
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
        self.enable_openlibrary_tool: bool = False
        self.enable_comicvine_tool: bool = False
        self.enable_musicbrainz_tool: bool = False
        self.retry_count: int = 0
        self.max_retries: int = 3
        self._missing_since: Optional[float] = None
        self.completed_file_path: Optional[str] = None
        self.group_id: Optional[str] = None  # Links files with same base name
        self.is_group_primary: bool = False  # First file in a group is primary
        self.destination_exists: bool = False  # True when library destination already taken
        self.force_overwrite: bool = False  # User explicitly chose to overwrite duplicate
        self.batch_id: Optional[str] = None  # Smart agent batch grouping
        self._batch_position: int = 0  # Position in batch (1-indexed for UI)
        self._batch_total: int = 0  # Total files in batch
        self._batch_message: str = ""  # Current agent status message for UI

    def to_dict(self) -> dict:
        return {
            'job_id': self.job_id,
            'original_path': self.original_path,
            'relative_path': self.relative_path,
            'status': self.status.value,
            'suggested_name': self.suggested_name,
            'new_path': self.new_path,
            'confidence': self.confidence,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'priority': self.priority,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'destination_exists': self.destination_exists,
            'force_overwrite': self.force_overwrite,
            'batch_id': self.batch_id,
            'batch_position': self._batch_position,
            'batch_total': self._batch_total,
            'batch_message': self._batch_message,
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
                old_status = job.status
                job.update_status(status, **kwargs)
                if status == JobStatus.PENDING_COMPLETION or old_status == JobStatus.PENDING_COMPLETION:
                    self._save_pending_jobs_locked()
                return True
            return False

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                was_pending = self._jobs[job_id].status == JobStatus.PENDING_COMPLETION
                del self._jobs[job_id]
                if was_pending:
                    self._save_pending_jobs_locked()
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

    def _save_pending_jobs_locked(self):
        """Persist all PENDING_COMPLETION jobs to JSON. Lock must be held."""
        pending_jobs = [j for j in self._jobs.values() if j.status == JobStatus.PENDING_COMPLETION]
        data = []
        for job in pending_jobs:
            data.append({
                'job_id': job.job_id,
                'original_path': job.original_path,
                'relative_path': job.relative_path,
                'status': job.status.value,
                'suggested_name': job.suggested_name,
                'new_path': job.new_path,
                'confidence': job.confidence,
                'created_at': job.created_at.isoformat(),
                'updated_at': job.updated_at.isoformat(),
                'custom_prompt': job.custom_prompt,
                'priority': job.priority,
                'include_instructions': job.include_instructions,
                'include_filename': job.include_filename,
                'enable_web_search': job.enable_web_search,
                'enable_tmdb_tool': job.enable_tmdb_tool,
                'enable_openlibrary_tool': job.enable_openlibrary_tool,
                'enable_comicvine_tool': job.enable_comicvine_tool,
                'enable_musicbrainz_tool': job.enable_musicbrainz_tool,
                'retry_count': job.retry_count,
                'max_retries': job.max_retries,
                'group_id': job.group_id,
                'is_group_primary': job.is_group_primary,
                'destination_exists': job.destination_exists,
                'force_overwrite': job.force_overwrite,
                'batch_id': job.batch_id,
            })
        try:
            with open(PENDING_JOBS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save pending jobs: {e}")

    def load_pending_jobs(self, downloading_path: str, completed_path: str) -> int:
        """Load PENDING_COMPLETION jobs from JSON. Returns count of restored jobs.
        Only restores jobs whose files still exist on disk."""
        if not os.path.exists(PENDING_JOBS_FILE):
            return 0
        
        try:
            with open(PENDING_JOBS_FILE, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending jobs: {e}")
            return 0
        
        loaded = 0
        for item in data:
            file_path = item.get('original_path', '')
            if not os.path.exists(file_path):
                alt_path = os.path.join(downloading_path, item.get('relative_path', ''))
                if os.path.exists(alt_path):
                    file_path = alt_path
                    item['original_path'] = alt_path
                else:
                    alt_path = os.path.join(completed_path, item.get('relative_path', ''))
                    if os.path.exists(alt_path):
                        file_path = alt_path
                        item['original_path'] = alt_path
                    else:
                        logger.info(f"Skipping pending job {item.get('job_id')}: file no longer exists at {item.get('relative_path')}")
                        continue
            
            with self._lock:
                job = Job(item['original_path'], item['relative_path'])
                job.job_id = item.get('job_id', job.job_id)
                job.status = JobStatus.PENDING_COMPLETION
                job.suggested_name = item.get('suggested_name') or item.get('ai_determined_name')
                job.new_path = item.get('new_path')
                job.confidence = item.get('confidence')
                job.created_at = datetime.fromisoformat(item['created_at'])
                job.updated_at = datetime.fromisoformat(item['updated_at'])
                job.custom_prompt = item.get('custom_prompt')
                job.priority = item.get('priority', False)
                job.include_instructions = item.get('include_instructions', True)
                job.include_filename = item.get('include_filename', True)
                job.enable_web_search = item.get('enable_web_search', False)
                job.enable_tmdb_tool = item.get('enable_tmdb_tool', False)
                job.enable_openlibrary_tool = item.get('enable_openlibrary_tool', False)
                job.enable_comicvine_tool = item.get('enable_comicvine_tool', False)
                job.enable_musicbrainz_tool = item.get('enable_musicbrainz_tool', False)
                job.retry_count = item.get('retry_count', 0)
                job.max_retries = item.get('max_retries', 3)
                job.group_id = item.get('group_id')
                job.is_group_primary = item.get('is_group_primary', False)
                job.destination_exists = item.get('destination_exists', False)
                job.force_overwrite = item.get('force_overwrite', False)
                job.batch_id = item.get('batch_id')
                self._jobs[job.job_id] = job
                loaded += 1
        
        logger.info(f"Restored {loaded} pending job(s) from {PENDING_JOBS_FILE}")
        return loaded

    def search_pending_jobs(self, query: str, max_results: int = 15) -> List[Dict]:
        """Search PENDING_COMPLETION jobs by query string. Designed for AI tool use.
        
        Args:
            query: Substring to match against relative_path and suggested_name.
            max_results: Maximum results to return (default 15).
            
        Returns:
            Compact list of {relative_path, suggested_name, confidence} dicts.
        """
        with self._lock:
            pending = [j for j in self._jobs.values() if j.status == JobStatus.PENDING_COMPLETION]
        
        query_lower = query.lower()
        results = []
        
        for job in pending:
            rel_path = (job.relative_path or '').lower()
            ai_name = (job.suggested_name or '').lower()
            
            if query_lower in rel_path or query_lower in ai_name:
                results.append({
                    'relative_path': job.relative_path,
                    'suggested_name': job.suggested_name,
                    'confidence': job.confidence,
                })
            
            if len(results) >= max_results:
                break
        
        return results

    def get_jobs_by_group(self, group_id: str) -> List[Job]:
        """Get all jobs that belong to the same group."""
        with self._lock:
            return [job for job in self._jobs.values() if job.group_id == group_id]
    
    def find_job_by_base_name(self, base_name: str) -> Optional[Job]:
        """Find existing job with same base name (without extension)."""
        with self._lock:
            for job in self._jobs.values():
                job_base_name = os.path.splitext(os.path.basename(job.relative_path))[0]
                if job_base_name == base_name:
                    return job
            return None

    def search_queue(self, query: str, max_results: int = 20,
                     include_completed: bool = False,
                     include_failed: bool = False) -> List[Dict]:
        """Search ALL jobs in the queue (not just PENDING_COMPLETION).
        
        Designed for the AI search_queue tool. Searches across QUEUED, PROCESSING,
        PENDING_COMPLETION, and AGENT_NAMED statuses.
        
        Args:
            query: Substring to match against relative_path and suggested_name.
            max_results: Maximum results to return.
            include_completed: Also search completed jobs.
            include_failed: Also search failed jobs.
            
        Returns:
            List of {job_id, relative_path, status, suggested_name, confidence, ext, batch_id} dicts.
        """
        with self._lock:
            all_jobs = list(self._jobs.values())
        
        query_lower = query.lower().strip()
        results = []
        
        for job in all_jobs:
            if not include_completed and job.status == JobStatus.COMPLETED:
                continue
            if not include_failed and job.status == JobStatus.FAILED:
                continue
            
            rel_path = (job.relative_path or '').lower()
            ai_name = (job.suggested_name or '').lower()
            base = os.path.splitext(os.path.basename(job.relative_path or ''))[0].lower()
            
            matched = False
            if not query_lower:
                matched = True
            elif query_lower in rel_path or query_lower in ai_name or query_lower in base:
                matched = True
            
            if matched:
                _, ext = os.path.splitext(job.relative_path or '')
                results.append({
                    'job_id': job.job_id,
                    'relative_path': job.relative_path,
                    'status': job.status.value,
                    'suggested_name': job.suggested_name,
                    'confidence': job.confidence,
                    'extension': ext,
                    'batch_id': job.batch_id,
                    'group_id': job.group_id,
                })
            
            if len(results) >= max_results:
                break
        
        return results

    def smart_group_jobs(self, pattern: str, job_ids: Optional[List[str]] = None) -> Dict:
        """Create a smart group from matching jobs or explicit job IDs.
        
        Args:
            pattern: Regex pattern to match job paths, or 'tv', 'book', 'multi_format'.
            job_ids: Optional explicit list of job IDs to group together.
            
        Returns:
            Dict with batch_id, count, and list of relative_paths.
        """
        import re
        
        with self._lock:
            if job_ids:
                target_jobs = [self._jobs[jid] for jid in job_ids if jid in self._jobs]
            else:
                target_jobs = [j for j in self._jobs.values()
                              if j.status in BATCH_PROCESSABLE_STATUSES]
            
            if pattern == 'tv':
                target_jobs = [j for j in target_jobs
                              if re.search(TV_EPISODE_PATTERN, os.path.basename(j.relative_path))]
            elif pattern == 'multi_format':
                target_jobs = [j for j in target_jobs
                              if os.path.splitext(j.relative_path)[1].lower() in
                              (MEDIA_EXTENSIONS | SUBTITLE_EXTENSIONS | BOOK_EXTENSIONS |
                               AUDIOBOOK_EXTENSIONS | COMIC_EXTENSIONS)]
            
            if not target_jobs:
                return {'batch_id': '', 'count': 0, 'files': []}
            
            batch_id = str(uuid.uuid4())
            for job in target_jobs:
                if job.status == JobStatus.QUEUED_FOR_AI:
                    job.batch_id = batch_id
                    job._batch_total = len(target_jobs)
            
            paths = [j.relative_path for j in target_jobs]
            return {
                'batch_id': batch_id,
                'count': len(target_jobs),
                'files': paths,
            }

    def get_jobs_by_batch(self, batch_id: str) -> List[Job]:
        """Get all jobs that belong to a smart agent batch."""
        with self._lock:
            return [j for j in self._jobs.values() if j.batch_id == batch_id]

    def update_job_batch_status(self, job_id: str, position: int = 0,
                                 total: int = 0, message: str = "") -> bool:
        """Update batch progress fields on a job (for UI display)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job._batch_position = position
                job._batch_total = total
                job._batch_message = message
                return True
            return False
