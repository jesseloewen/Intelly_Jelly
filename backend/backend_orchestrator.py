import os
import shutil
import threading
import time
import logging
from typing import List, Optional
from pathlib import Path

from backend.job_store import JobStore, JobStatus
from backend.config_manager import ConfigManager
from backend.ai_processor import AIProcessor
from backend.file_watcher import (
    FileWatcher, 
    DownloadingFolderHandler, 
    CompletedFolderHandler
)

logger = logging.getLogger(__name__)


class BackendOrchestrator:
    def __init__(self, config_manager: ConfigManager, job_store: JobStore):
        self.config_manager = config_manager
        self.job_store = job_store
        self.ai_processor = AIProcessor(config_manager)
        
        self.downloading_watcher: Optional[FileWatcher] = None
        self.completed_watcher: Optional[FileWatcher] = None
        
        self.queue_thread: Optional[threading.Thread] = None
        self.queue_running = False
        
        self._running = False
        
        self.config_manager.register_change_callback(self._on_config_change)

    def start(self):
        if self._running:
            logger.warning("Backend orchestrator already running, ignoring start request")
            return
        
        self._running = True
        logger.info("Starting backend orchestrator...")
        
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        completed_path = self.config_manager.get('COMPLETED_PATH')
        
        logger.info(f"Monitoring downloading folder: {downloading_path}")
        logger.info(f"Monitoring completed folder: {completed_path}")
        
        downloading_handler = DownloadingFolderHandler(self._on_file_detected, downloading_path)
        self.downloading_watcher = FileWatcher(downloading_path, downloading_handler)
        self.downloading_watcher.start()
        logger.debug("Downloading folder watcher started")
        
        completed_handler = CompletedFolderHandler(self._on_file_completed, completed_path)
        self.completed_watcher = FileWatcher(completed_path, completed_handler)
        self.completed_watcher.start()
        logger.debug("Completed folder watcher started")
        
        self.queue_running = True
        self.queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self.queue_thread.start()
        logger.debug("Queue worker thread started")
        
        logger.info("Backend orchestrator started successfully")

    def stop(self):
        if not self._running:
            logger.warning("Backend orchestrator not running, ignoring stop request")
            return
        
        logger.info("Stopping backend orchestrator...")
        
        self._running = False
        self.queue_running = False
        
        if self.downloading_watcher:
            self.downloading_watcher.stop()
            logger.debug("Downloading folder watcher stopped")
        
        if self.completed_watcher:
            self.completed_watcher.stop()
            logger.debug("Completed folder watcher stopped")
        
        if self.queue_thread:
            self.queue_thread.join(timeout=5)
            logger.debug("Queue worker thread stopped")
        
        logger.info("Backend orchestrator stopped successfully")

    def _on_file_detected(self, file_path: str, relative_path: str):
        logger.info(f"File detected in downloading folder: {relative_path}")
        logger.debug(f"Full path: {file_path}")
        
        existing_job = self.job_store.get_job_by_path(file_path)
        if existing_job:
            logger.warning(f"Job already exists for {relative_path} (job_id: {existing_job.job_id})")
            return
        
        job = self.job_store.add_job(file_path, relative_path)
        logger.info(f"Created job {job.job_id} for {relative_path} - added to queue")
        # Job is now in queue and will be processed by queue worker

    def _queue_worker(self):
        """Process jobs one at a time from the queue."""
        logger.info("Queue worker started - processing one job at a time")
        
        while self.queue_running:
            try:
                # First check for priority jobs (re-AI requests)
                priority_jobs = self.job_store.get_priority_jobs()
                
                if priority_jobs:
                    job = priority_jobs[0]
                    logger.info(f"Processing priority job: {job.job_id} ({job.relative_path})")
                    self._process_single_job(job, is_priority=True)
                else:
                    # Process regular queued jobs one at a time
                    queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
                    non_priority_jobs = [j for j in queued_jobs if not j.priority]
                    
                    if non_priority_jobs:
                        job = non_priority_jobs[0]
                        logger.info(f"Processing queued job: {job.job_id} ({job.relative_path})")
                        self._process_single_job(job, is_priority=False)
                
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"Error in queue worker: {type(e).__name__}: {e}", exc_info=True)
                time.sleep(1)
    
    def _process_single_job(self, job, is_priority: bool = False):
        """Process a single job through AI."""
        self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        logger.debug(f"Updated job {job.job_id} to PROCESSING_AI status")
        
        try:
            # Get job settings
            custom_prompt = getattr(job, 'custom_prompt', None)
            include_instructions = getattr(job, 'include_instructions', True)
            include_filename = getattr(job, 'include_filename', True)
            enable_web_search = getattr(job, 'enable_web_search', self.config_manager.get('ENABLE_WEB_SEARCH', False))
            
            logger.debug(f"Job {job.job_id} settings: custom_prompt={bool(custom_prompt)}, include_instructions={include_instructions}, include_filename={include_filename}, web_search={enable_web_search}")
            
            # Process single file
            result = self.ai_processor.process_single(
                job.relative_path,
                custom_prompt=custom_prompt,
                include_default=include_instructions,
                include_filename=include_filename,
                enable_web_search=enable_web_search
            )
            
            if result:
                suggested_name = result.get('suggested_name')
                confidence = result.get('confidence', 0)
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.PENDING_COMPLETION,
                    ai_determined_name=suggested_name,
                    confidence=confidence,
                    priority=False if is_priority else job.priority
                )
                logger.info(f"Job {job.job_id} completed: {job.relative_path} -> {suggested_name} (confidence: {confidence}%)")
            else:
                logger.warning(f"No AI result returned for job {job.job_id}")
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.FAILED,
                    error_message="No AI result returned",
                    priority=False if is_priority else job.priority
                )
        
        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {type(e).__name__}: {e}", exc_info=True)
            self.job_store.update_job(
                job.job_id,
                JobStatus.FAILED,
                error_message=str(e),
                priority=False if is_priority else job.priority
            )

    def _on_file_completed(self, file_path: str, relative_path: str):
        logger.info(f"File appeared in completed folder: {relative_path}")
        logger.debug(f"Full path: {file_path}")
        
        job = self.job_store.get_job_by_path(relative_path)
        
        if not job:
            filename = os.path.basename(file_path)
            logger.debug(f"Job not found by relative path, trying filename: {filename}")
            job = self.job_store.get_job_by_path(filename)
        
        if not job:
            logger.debug("Job not found by filename, searching all jobs by relative path")
            for j in self.job_store.get_all_jobs():
                if j.relative_path == relative_path:
                    job = j
                    break
        
        if not job:
            filename = os.path.basename(file_path)
            logger.debug("Job not found by relative path, searching all jobs by basename")
            for j in self.job_store.get_all_jobs():
                if os.path.basename(j.original_path) == filename:
                    job = j
                    break
        
        if not job:
            logger.warning(f"No matching job found for {relative_path}")
            return
        
        logger.info(f"Found matching job {job.job_id} for {relative_path}")
        
        if job.status != JobStatus.PENDING_COMPLETION and job.status != JobStatus.MANUAL_EDIT:
            logger.warning(f"Job {job.job_id} is not ready for completion (status: {job.status.value})")
            return
        
        self._organize_file(job, file_path)

    def _organize_file(self, job, file_path: str):
        library_path = self.config_manager.get('LIBRARY_PATH')
        dry_run = self.config_manager.get('DRY_RUN_MODE', False)
        
        logger.info(f"Organizing file for job {job.job_id}: {file_path}")
        logger.debug(f"Library path: {library_path}, Dry run: {dry_run}")
        
        new_name = job.ai_determined_name or os.path.basename(file_path)
        logger.debug(f"Target name: {new_name}")
        
        if job.new_path:
            destination_dir = os.path.join(library_path, os.path.dirname(job.new_path))
            destination_file = os.path.join(library_path, job.new_path)
            logger.debug(f"Using custom path: {job.new_path}")
        else:
            destination_file = os.path.join(library_path, new_name)
            destination_dir = os.path.dirname(destination_file)
            if not destination_dir or destination_dir == library_path:
                destination_dir = library_path
        
        logger.debug(f"Destination directory: {destination_dir}")
        logger.debug(f"Destination file: {destination_file}")
        
        try:
            os.makedirs(destination_dir, exist_ok=True)
            logger.debug(f"Created/verified destination directory: {destination_dir}")
            
            if os.path.exists(destination_file):
                logger.warning(f"Destination file already exists: {destination_file}, finding unique name")
                base, ext = os.path.splitext(new_name)
                counter = 1
                while os.path.exists(destination_file):
                    new_name = f"{base}_{counter}{ext}"
                    destination_file = os.path.join(destination_dir, new_name)
                    counter += 1
                logger.info(f"Using unique filename: {new_name}")
            
            if dry_run:
                logger.info(f"DRY RUN: Would move {file_path} -> {destination_file}")
            else:
                shutil.move(file_path, destination_file)
                logger.info(f"Successfully moved file: {file_path} -> {destination_file}")
            
            self.job_store.update_job(
                job.job_id,
                JobStatus.COMPLETED,
                new_path=destination_file
            )
            logger.info(f"Job {job.job_id} marked as COMPLETED")
            
            # Auto-remove completed job from store after 1 second
            # This gives the UI time to display completion status before removal
            def remove_completed_job():
                time.sleep(1)
                if self.job_store.delete_job(job.job_id):
                    logger.info(f"Job {job.job_id} automatically removed from store after completion")
                else:
                    logger.warning(f"Failed to auto-remove completed job {job.job_id}")
            
            removal_thread = threading.Thread(target=remove_completed_job, daemon=True)
            removal_thread.start()
        
        except Exception as e:
            logger.error(f"Error organizing file for job {job.job_id}: {type(e).__name__}: {e}", exc_info=True)
            self.job_store.update_job(
                job.job_id,
                JobStatus.FAILED,
                error_message=str(e)
            )

    def _on_config_change(self, old_config, new_config):
        logger.info("Configuration changed, updating watchers...")
        logger.debug(f"Old config keys: {list(old_config.keys())}")
        logger.debug(f"New config keys: {list(new_config.keys())}")
        
        if old_config.get('DOWNLOADING_PATH') != new_config.get('DOWNLOADING_PATH'):
            new_downloading_path = new_config.get('DOWNLOADING_PATH')
            logger.info(f"Downloading path changed: {old_config.get('DOWNLOADING_PATH')} -> {new_downloading_path}")
            if self.downloading_watcher:
                self.downloading_watcher.handler.update_base_path(new_downloading_path)
                self.downloading_watcher.restart(new_downloading_path)
                logger.debug("Downloading watcher restarted with new path")
        
        if old_config.get('COMPLETED_PATH') != new_config.get('COMPLETED_PATH'):
            new_completed_path = new_config.get('COMPLETED_PATH')
            logger.info(f"Completed path changed: {old_config.get('COMPLETED_PATH')} -> {new_completed_path}")
            if self.completed_watcher:
                self.completed_watcher.handler.update_base_path(new_completed_path)
                self.completed_watcher.restart(new_completed_path)
                logger.debug("Completed watcher restarted with new path")

    def manual_edit_job(self, job_id: str, new_name: str, new_path: Optional[str] = None):
        logger.info(f"Manual edit requested for job {job_id}")
        logger.debug(f"New name: {new_name}, New path: {new_path}")
        
        job = self.job_store.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for manual edit")
            return False
        
        logger.info(f"Updating job {job_id} with manual edits")
        self.job_store.update_job(
            job_id,
            JobStatus.MANUAL_EDIT,
            ai_determined_name=new_name,
            new_path=new_path
        )
        
        self.job_store.update_job(job_id, JobStatus.PENDING_COMPLETION)
        logger.info(f"Job {job_id} marked as PENDING_COMPLETION after manual edit")
        
        return True

    def re_ai_job(self, job_id: str, custom_prompt: Optional[str] = None, include_instructions: bool = True, include_filename: bool = True, enable_web_search: bool = False):
        logger.info(f"Re-AI requested for job {job_id}")
        logger.debug(f"Custom prompt: {bool(custom_prompt)}, Include instructions: {include_instructions}, Include filename: {include_filename}, Web search: {enable_web_search}")
        
        job = self.job_store.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for re-AI")
            return False
        
        logger.info(f"Queueing job {job_id} for priority AI processing")
        self.job_store.update_job(
            job_id,
            JobStatus.QUEUED_FOR_AI,
            custom_prompt=custom_prompt,
            priority=True,
            include_instructions=include_instructions,
            include_filename=include_filename,
            enable_web_search=enable_web_search
        )
        logger.info(f"Job {job_id} marked as QUEUED_FOR_AI with priority=True")
        
        return True
