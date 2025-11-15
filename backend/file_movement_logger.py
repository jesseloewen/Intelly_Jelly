import json
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class FileMovementLogger:
    """Thread-safe logger for tracking file movements from source to destination."""
    
    def __init__(self, log_file_path: str = 'file_movements.json'):
        self.log_file_path = log_file_path
        self._lock = threading.RLock()
        self._ensure_log_file_exists()
    
    def _ensure_log_file_exists(self):
        """Create the log file if it doesn't exist."""
        if not os.path.exists(self.log_file_path):
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            logger.info(f"Created new file movement log at {self.log_file_path}")
    
    def _read_logs(self) -> List[Dict]:
        """Read all logs from the file."""
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Error reading log file: {e}, returning empty list")
            return []
    
    def _write_logs(self, logs: List[Dict]):
        """Write logs to the file."""
        with open(self.log_file_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    
    def log_movement(self, source_path: str, destination_path: str, 
                    job_id: Optional[str] = None, status: str = 'success',
                    error_message: Optional[str] = None):
        """
        Log a file movement operation.
        
        Args:
            source_path: Original file location
            destination_path: New file location
            job_id: Optional job ID for tracking
            status: 'success' or 'failed'
            error_message: Optional error message if status is 'failed'
        """
        with self._lock:
            logs = self._read_logs()
            
            movement_entry = {
                'timestamp': datetime.now().isoformat(),
                'source_path': source_path,
                'destination_path': destination_path,
                'source_filename': os.path.basename(source_path),
                'destination_filename': os.path.basename(destination_path),
                'status': status,
                'job_id': job_id,
                'error_message': error_message
            }
            
            logs.append(movement_entry)
            self._write_logs(logs)
            
            logger.info(f"Logged file movement: {source_path} -> {destination_path} (status: {status})")
    
    def get_all_movements(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get all logged file movements.
        
        Args:
            limit: Optional limit on number of entries to return (most recent first)
            
        Returns:
            List of movement log entries
        """
        with self._lock:
            logs = self._read_logs()
            # Return most recent first
            logs.reverse()
            
            if limit:
                return logs[:limit]
            return logs
    
    def get_movements_by_status(self, status: str) -> List[Dict]:
        """Get all movements with a specific status."""
        with self._lock:
            logs = self._read_logs()
            return [log for log in logs if log.get('status') == status]
    
    def get_movements_by_job_id(self, job_id: str) -> List[Dict]:
        """Get all movements associated with a specific job ID."""
        with self._lock:
            logs = self._read_logs()
            return [log for log in logs if log.get('job_id') == job_id]
    
    def clear_logs(self):
        """Clear all movement logs."""
        with self._lock:
            self._write_logs([])
            logger.info("Cleared all file movement logs")
    
    def get_stats(self) -> Dict:
        """Get statistics about file movements."""
        with self._lock:
            logs = self._read_logs()
            
            return {
                'total_movements': len(logs),
                'successful_movements': len([l for l in logs if l.get('status') == 'success']),
                'failed_movements': len([l for l in logs if l.get('status') == 'failed']),
                'latest_movement': logs[-1] if logs else None
            }
