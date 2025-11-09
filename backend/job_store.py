"""
Job Store
Thread-safe storage for tracking file processing jobs using SQLite.
"""

import sqlite3
import threading
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import uuid


class JobStatus:
    """Job status constants."""
    QUEUED_FOR_AI = "queued_for_ai"
    PROCESSING_AI = "processing_ai"
    PENDING_COMPLETION = "pending_completion"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_EDIT = "manual_edit"


class JobStore:
    """Thread-safe job tracking with SQLite persistence."""
    
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    original_path TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    new_name TEXT,
                    subfolder TEXT,
                    ai_response TEXT,
                    error_message TEXT,
                    custom_prompt TEXT,
                    priority INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Create index on status for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_priority ON jobs(priority DESC, created_at)
            """)
            
            conn.commit()
            conn.close()
    
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_job(self, original_path: str, status: str = JobStatus.QUEUED_FOR_AI) -> str:
        """Create a new job and return its ID."""
        with self._lock:
            job_id = str(uuid.uuid4())
            original_filename = Path(original_path).name
            now = datetime.utcnow().isoformat()
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO jobs (
                    job_id, original_path, original_filename, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, original_path, original_filename, status, now, now))
            
            conn.commit()
            conn.close()
            
            return job_id
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
    
    def get_job_by_filename(self, filename: str, status: str = None) -> Optional[Dict[str, Any]]:
        """Get a job by original filename, optionally filtered by status."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if status:
                cursor.execute(
                    "SELECT * FROM jobs WHERE original_filename = ? AND status = ? ORDER BY created_at DESC LIMIT 1",
                    (filename, status)
                )
            else:
                cursor.execute(
                    "SELECT * FROM jobs WHERE original_filename = ? ORDER BY created_at DESC LIMIT 1",
                    (filename,)
                )
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update a job with new values."""
        with self._lock:
            if not updates:
                return False
            
            updates['updated_at'] = datetime.utcnow().isoformat()
            
            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values()) + [job_id]
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                f"UPDATE jobs SET {set_clause} WHERE job_id = ?",
                values
            )
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            return affected > 0
    
    def get_jobs_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get all jobs with a specific status."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY priority DESC, created_at",
                (status,)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_all_jobs(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get all jobs, ordered by most recent first."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_active_jobs(self) -> List[Dict[str, Any]]:
        """Get all active (non-completed, non-failed) jobs."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status NOT IN (?, ?)
                ORDER BY priority DESC, created_at
            """, (JobStatus.COMPLETED, JobStatus.FAILED))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            return affected > 0
    
    def clear_completed(self, days_old: int = 7) -> int:
        """Clear completed jobs older than specified days."""
        with self._lock:
            cutoff = datetime.utcnow().timestamp() - (days_old * 86400)
            cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM jobs 
                WHERE status = ? AND updated_at < ?
            """, (JobStatus.COMPLETED, cutoff_iso))
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            return affected


# Global job store instance
_store_instance = None
_store_lock = threading.Lock()


def get_job_store() -> JobStore:
    """Get the global job store instance."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = JobStore()
    return _store_instance
