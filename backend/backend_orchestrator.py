import os
import shutil
import threading
import time
import logging
import requests
import uuid
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
from backend.file_movement_logger import FileMovementLogger

logger = logging.getLogger(__name__)


class BackendOrchestrator:
    def __init__(self, config_manager: ConfigManager, job_store: JobStore):
        self.config_manager = config_manager
        self.job_store = job_store
        self.ai_processor = AIProcessor(config_manager)
        self.file_movement_logger = FileMovementLogger()
        
        self.downloading_watcher: Optional[FileWatcher] = None
        self.completed_watcher: Optional[FileWatcher] = None
        self.uploads_watcher: Optional[FileWatcher] = None
        
        self.queue_thread: Optional[threading.Thread] = None
        self.queue_running = False
        
        self._running = False
        self._last_processing_time = time.time()  # Track last time we processed something
        self._stall_timeout = 30  # seconds before considering queue stalled
        
        self.config_manager.register_change_callback(self._on_config_change)

    def start(self):
        if self._running:
            logger.warning("Backend orchestrator already running, ignoring start request")
            return
        
        self._running = True
        logger.info("Starting backend orchestrator...")
        
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        completed_path = self.config_manager.get('COMPLETED_PATH')
        uploads_path = self.config_manager.get('UPLOADS_PATH')
        
        logger.info(f"Monitoring downloading folder: {downloading_path}")
        logger.info(f"Monitoring completed folder: {completed_path}")
        logger.info(f"Monitoring uploads folder: {uploads_path}")
        
        downloading_handler = DownloadingFolderHandler(lambda fp, rp: self._on_file_detected(fp, rp, 'downloading'), downloading_path)
        self.downloading_watcher = FileWatcher(downloading_path, downloading_handler)
        self.downloading_watcher.start()
        logger.debug("Downloading folder watcher started")
        
        completed_handler = CompletedFolderHandler(self._on_file_completed, completed_path)
        self.completed_watcher = FileWatcher(completed_path, completed_handler)
        self.completed_watcher.start()
        logger.debug("Completed folder watcher started")
        
        # Start uploads watcher (processed same as downloading)
        uploads_handler = DownloadingFolderHandler(lambda fp, rp: self._on_file_detected(fp, rp, 'uploads'), uploads_path)
        self.uploads_watcher = FileWatcher(uploads_path, uploads_handler)
        self.uploads_watcher.start()
        logger.debug("Uploads folder watcher started")
        
        self.queue_running = True
        self.queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self.queue_thread.start()
        logger.debug("Queue worker thread started")
        
        # Scan for existing files in both folders
        self._scan_existing_files()
        
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
        
        if self.uploads_watcher:
            self.uploads_watcher.stop()
            logger.debug("Uploads folder watcher stopped")
        
        if self.queue_thread:
            self.queue_thread.join(timeout=5)
            logger.debug("Queue worker thread stopped")
        
        logger.info("Backend orchestrator stopped successfully")

    def _on_file_detected(self, file_path: str, relative_path: str, source_folder: str = 'downloading'):
        logger.info(f"File detected in {source_folder} folder: {relative_path}")
        logger.debug(f"Full path: {file_path}")
        
        existing_job = self.job_store.get_job_by_path(file_path)
        if existing_job:
            logger.warning(f"Job already exists for {relative_path} (job_id: {existing_job.job_id})")
            return
        
        # Check if there's an existing job with the same base name AND in the same directory (for grouping)
        # This ensures files in different subdirectories are not grouped together
        file_dir = os.path.dirname(relative_path)
        base_name = os.path.splitext(os.path.basename(relative_path))[0]
        
        # Find existing job with same base name in the same directory
        existing_group_job = None
        for job in self.job_store.get_all_jobs():
            job_dir = os.path.dirname(job.relative_path)
            job_base_name = os.path.splitext(os.path.basename(job.relative_path))[0]
            if job_base_name == base_name and job_dir == file_dir:
                existing_group_job = job
                break
        
        job = self.job_store.add_job(file_path, relative_path)
        # Track which folder this file came from
        job.source_folder = source_folder
        # Apply default web search and TMDB tool settings from config
        job.enable_web_search = self.config_manager.get('ENABLE_WEB_SEARCH', False)
        job.enable_tmdb_tool = self.config_manager.get('ENABLE_TMDB_TOOL', False)
        
        if existing_group_job and existing_group_job.group_id:
            # Add this job to the existing group
            job.group_id = existing_group_job.group_id
            logger.info(f"Created job {job.job_id} for {relative_path} - added to group {job.group_id}")
        elif existing_group_job:
            # Create a new group for both files
            group_id = str(uuid.uuid4())
            existing_group_job.group_id = group_id
            existing_group_job.is_group_primary = True
            job.group_id = group_id
            logger.info(f"Created job {job.job_id} for {relative_path} - created group {group_id} with {existing_group_job.job_id}")
        else:
            # Single file, mark as primary
            job.is_group_primary = True
            logger.info(f"Created job {job.job_id} for {relative_path} - added to queue (web_search={job.enable_web_search}, tmdb_tool={job.enable_tmdb_tool}, source={source_folder})")
        
        # Job is now in queue and will be processed by queue worker

    def _scan_existing_files(self):
        """
        Scan both downloading and completed folders for existing files at startup and create jobs for them.
        """
        # Scan downloading folder
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        if os.path.exists(downloading_path):
            logger.info(f"Scanning for existing files in: {downloading_path}")
            downloading_count = 0
            
            for root, dirs, files in os.walk(downloading_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, downloading_path)
                    self._on_file_detected(file_path, relative_path, 'downloading')
                    downloading_count += 1
            
            if downloading_count > 0:
                logger.info(f"Found {downloading_count} existing file(s) in downloading folder")
            else:
                logger.info("No existing files found in downloading folder")
        else:
            logger.warning(f"Downloading folder does not exist: {downloading_path}")
        
        # Scan completed folder
        completed_path = self.config_manager.get('COMPLETED_PATH')
        if os.path.exists(completed_path):
            logger.info(f"Scanning for existing files in: {completed_path}")
            completed_count = 0
            
            for root, dirs, files in os.walk(completed_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, completed_path)
                    self._on_file_completed(file_path, relative_path)
                    completed_count += 1
            
            if completed_count > 0:
                logger.info(f"Found {completed_count} existing file(s) in completed folder")
            else:
                logger.info("No existing files found in completed folder")
        else:
            logger.warning(f"Completed folder does not exist: {completed_path}")
        
        # Scan uploads folder (same as downloading)
        uploads_path = self.config_manager.get('UPLOADS_PATH')
        if os.path.exists(uploads_path):
            logger.info(f"Scanning for existing files in: {uploads_path}")
            uploads_count = 0
            
            for root, dirs, files in os.walk(uploads_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, uploads_path)
                    self._on_file_detected(file_path, relative_path, 'uploads')
                    uploads_count += 1
            
            if uploads_count > 0:
                logger.info(f"Found {uploads_count} existing file(s) in uploads folder")
            else:
                logger.info("No existing files found in uploads folder")
        else:
            logger.warning(f"Uploads folder does not exist: {uploads_path}")

    def _check_stalled_queue(self):
        """
        Check if there are queued jobs but none processing for an extended period,
        indicating a stalled queue.
        """
        queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
        processing_jobs = self.job_store.get_jobs_by_status(JobStatus.PROCESSING_AI)
        
        # Explicitly exclude failed jobs from the queued list (extra safety check)
        queued_jobs = [j for j in queued_jobs if j.status != JobStatus.FAILED]
        
        if queued_jobs and not processing_jobs:
            # Check how long it's been since we last processed something
            time_since_last_processing = time.time() - self._last_processing_time
            
            if time_since_last_processing > self._stall_timeout:
                logger.warning(f"Detected stalled queue: {len(queued_jobs)} jobs queued but none processing for {time_since_last_processing:.1f}s. Forcing processing to resume.")
                
                # Reset the timer to avoid repeated warnings
                self._last_processing_time = time.time()
                
                # Force process a job to break the stall
                # Prioritize single files over grouped files to break potential group deadlocks
                non_grouped_jobs = [j for j in queued_jobs if not j.group_id or j.is_group_primary]
                if non_grouped_jobs:
                    return True
        
        return False
    
    def _queue_worker(self):
        """Process jobs one at a time from the queue."""
        logger.info("Queue worker started - processing one job at a time")
        
        while self.queue_running:
            try:
                # Check for missing files in downloading folder and remove stale jobs
                self._check_and_remove_missing_files()
                
                # Check for stalled queue condition
                if self._check_stalled_queue():
                    logger.info("Queue was stalled, resuming processing")
                
                # First check for priority jobs (re-AI requests)
                priority_jobs = self.job_store.get_priority_jobs()
                
                if priority_jobs:
                    job = priority_jobs[0]
                    logger.info(f"Processing priority job: {job.job_id} ({job.relative_path})")
                    self._process_single_job(job, is_priority=True)
                    self._last_processing_time = time.time()  # Reset stall timer
                else:
                    # Process regular queued jobs one at a time (or groups together)
                    queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
                    non_priority_jobs = [j for j in queued_jobs if not j.priority]
                    
                    if non_priority_jobs:
                        job = non_priority_jobs[0]
                        
                        # Check if this job is part of a group
                        if job.group_id and job.is_group_primary:
                            # Get all jobs in this group
                            group_jobs = self.job_store.get_jobs_by_group(job.group_id)
                            # Filter to only queued jobs
                            group_queued = [j for j in group_jobs if j.status == JobStatus.QUEUED_FOR_AI]
                            
                            if len(group_queued) == len(group_jobs):
                                # All files in group are ready, process together
                                logger.info(f"Processing grouped jobs: {len(group_jobs)} files with same base name")
                                self._process_grouped_jobs(group_jobs, is_priority=False)
                                self._last_processing_time = time.time()  # Reset stall timer
                            else:
                                # Wait for all files in group to be queued
                                logger.debug(f"Waiting for all files in group {job.group_id} to be ready ({len(group_queued)}/{len(group_jobs)})")
                        elif job.is_group_primary or not job.group_id:
                            # Single file or primary file without group
                            logger.info(f"Processing queued job: {job.job_id} ({job.relative_path})")
                            self._process_single_job(job, is_priority=False)
                            self._last_processing_time = time.time()  # Reset stall timer
                        else:
                            # Secondary file in group, skip (will be processed with primary)
                            logger.debug(f"Skipping secondary file {job.job_id}, waiting for primary file in group")
                    else:
                        # If no queued jobs, check for failed jobs to retry
                        # Only retry after all other jobs are complete
                        failed_jobs = self.job_store.get_failed_jobs_for_retry()
                        if failed_jobs:
                            job = failed_jobs[0]
                            logger.info(f"Retrying failed job: {job.job_id} ({job.relative_path}) - Attempt {job.retry_count + 1}/{job.max_retries}")
                            self._process_single_job(job, is_priority=False, is_retry=True)
                            self._last_processing_time = time.time()  # Reset stall timer
                
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"Error in queue worker: {type(e).__name__}: {e}", exc_info=True)
                time.sleep(1)
    
    def _process_grouped_jobs(self, jobs: List, is_priority: bool = False):
        """Process a group of jobs with the same base name together through AI."""
        # Mark all jobs as processing
        for job in jobs:
            self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        
        logger.info(f"Processing group of {len(jobs)} files together")
        
        try:
            # Use settings from primary job
            primary_job = next((j for j in jobs if j.is_group_primary), jobs[0])
            custom_prompt = getattr(primary_job, 'custom_prompt', None)
            include_instructions = getattr(primary_job, 'include_instructions', True)
            include_filename = getattr(primary_job, 'include_filename', True)
            enable_web_search = getattr(primary_job, 'enable_web_search', self.config_manager.get('ENABLE_WEB_SEARCH', False))
            enable_tmdb_tool = getattr(primary_job, 'enable_tmdb_tool', self.config_manager.get('ENABLE_TMDB_TOOL', False))
            
            # Process all files together
            file_paths = [job.relative_path for job in jobs]
            results = self.ai_processor.process_batch(
                file_paths,
                custom_prompt=custom_prompt,
                include_default=include_instructions,
                include_filename=include_filename,
                enable_web_search=enable_web_search,
                enable_tmdb_tool=enable_tmdb_tool
            )
            
            if results and len(results) == len(jobs):
                # Ensure all files in the group use the same directory structure
                # Find the primary job (typically the main video file)
                primary_job_idx = next((i for i, j in enumerate(jobs) if j.is_group_primary), 0)
                primary_result = results[primary_job_idx]
                primary_suggested_name = primary_result.get('suggested_name', '')
                
                # Extract the directory path from the primary file
                if '/' in primary_suggested_name or '\\' in primary_suggested_name:
                    # Normalize path separators
                    primary_suggested_name_normalized = primary_suggested_name.replace('\\', '/')
                    primary_dir = os.path.dirname(primary_suggested_name_normalized)
                    logger.info(f"Group directory structure from primary file: {primary_dir}")
                else:
                    primary_dir = ''
                
                # Apply results to each job, ensuring they use the same directory
                for job, result in zip(jobs, results):
                    suggested_name = result.get('suggested_name')
                    confidence = result.get('confidence', 0)
                    
                    # If this is not the primary file, adjust its path to match the primary's directory
                    if job != jobs[primary_job_idx] and suggested_name:
                        suggested_name_normalized = suggested_name.replace('\\', '/')
                        # Get just the filename from the suggested name
                        filename = os.path.basename(suggested_name_normalized)
                        
                        # Combine with primary directory
                        if primary_dir:
                            suggested_name = f"{primary_dir}/{filename}"
                            logger.info(f"Adjusted grouped file path: {result.get('suggested_name')} -> {suggested_name}")
                        else:
                            suggested_name = filename
                    
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.PENDING_COMPLETION,
                        ai_determined_name=suggested_name,
                        confidence=confidence,
                        priority=False if is_priority else job.priority
                    )
                    logger.info(f"Job {job.job_id} completed: {job.relative_path} -> {suggested_name} (confidence: {confidence}%)")
                    
                    # If file came from uploads folder, move it to completed folder
                    if job.source_folder == 'uploads':
                        self._move_uploads_to_completed(job)
                    
                    # If file is already waiting in completed folder, organize it now
                    if job.completed_file_path and os.path.exists(job.completed_file_path):
                        logger.info(f"Job {job.job_id} file already in completed folder, organizing now")
                        self._organize_file(job, job.completed_file_path)
            else:
                logger.warning(f"AI results mismatch for grouped jobs: expected {len(jobs)}, got {len(results) if results else 0}")
                # Mark all as failed
                for job in jobs:
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.FAILED,
                        error_message="AI result mismatch for grouped files",
                        priority=False if is_priority else job.priority
                    )
        
        except Exception as e:
            logger.error(f"Error processing grouped jobs: {type(e).__name__}: {e}", exc_info=True)
            # Mark all jobs as failed
            for job in jobs:
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.FAILED,
                    error_message=str(e),
                    priority=False if is_priority else job.priority
                )
    
    def _process_single_job(self, job, is_priority: bool = False, is_retry: bool = False):
        """Process a single job through AI."""
        self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        logger.debug(f"Updated job {job.job_id} to PROCESSING_AI status")
        
        try:
            # Get job settings
            custom_prompt = getattr(job, 'custom_prompt', None)
            include_instructions = getattr(job, 'include_instructions', True)
            include_filename = getattr(job, 'include_filename', True)
            enable_web_search = getattr(job, 'enable_web_search', self.config_manager.get('ENABLE_WEB_SEARCH', False))
            enable_tmdb_tool = getattr(job, 'enable_tmdb_tool', self.config_manager.get('ENABLE_TMDB_TOOL', False))
            
            logger.debug(f"Job {job.job_id} settings: custom_prompt={bool(custom_prompt)}, include_instructions={include_instructions}, include_filename={include_filename}, web_search={enable_web_search}, tmdb_tool={enable_tmdb_tool}")
            
            # Process single file
            result = self.ai_processor.process_single(
                job.relative_path,
                custom_prompt=custom_prompt,
                include_default=include_instructions,
                include_filename=include_filename,
                enable_web_search=enable_web_search,
                enable_tmdb_tool=enable_tmdb_tool
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
                
                # If file came from uploads folder, move it to completed folder
                if job.source_folder == 'uploads':
                    self._move_uploads_to_completed(job)
                
                # If file is already waiting in completed folder, organize it now
                if job.completed_file_path and os.path.exists(job.completed_file_path):
                    logger.info(f"Job {job.job_id} file already in completed folder, organizing now")
                    self._organize_file(job, job.completed_file_path)
            else:
                logger.warning(f"No AI result returned for job {job.job_id}")
                # Increment retry count if this is a retry attempt
                if is_retry:
                    job.retry_count += 1
                    if job.retry_count >= job.max_retries:
                        logger.error(f"Job {job.job_id} exceeded max retries ({job.max_retries})")
                
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.FAILED,
                    error_message="No AI result returned",
                    priority=False if is_priority else job.priority
                )
        
        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {type(e).__name__}: {e}", exc_info=True)
            # Increment retry count if this is a retry attempt
            if is_retry:
                job.retry_count += 1
                if job.retry_count >= job.max_retries:
                    logger.error(f"Job {job.job_id} exceeded max retries ({job.max_retries})")
            
            self.job_store.update_job(
                job.job_id,
                JobStatus.FAILED,
                error_message=str(e),
                priority=False if is_priority else job.priority
            )

    def _on_file_completed(self, file_path: str, relative_path: str):
        logger.info(f"File detected in completed folder: {relative_path}")
        logger.debug(f"Full path: {file_path}")
        
        # Check if job already exists for this file
        existing_job = self.job_store.get_job_by_path(file_path)
        if existing_job:
            logger.info(f"Job already exists for {relative_path} (job_id: {existing_job.job_id})") 
            return
        
        # No existing job, create a new one (same logic as downloading folder)
        file_dir = os.path.dirname(relative_path)
        base_name = os.path.splitext(os.path.basename(relative_path))[0]
        
        # Find existing job with same base name in the same directory
        existing_group_job = None
        for job in self.job_store.get_all_jobs():
            job_dir = os.path.dirname(job.relative_path)
            job_base_name = os.path.splitext(os.path.basename(job.relative_path))[0]
            if job_base_name == base_name and job_dir == file_dir:
                existing_group_job = job
                break
        
        job = self.job_store.add_job(file_path, relative_path)
        # Track that this came from completed folder
        job.source_folder = 'completed'
        # Apply default web search and TMDB tool settings from config
        job.enable_web_search = self.config_manager.get('ENABLE_WEB_SEARCH', False)
        job.enable_tmdb_tool = self.config_manager.get('ENABLE_TMDB_TOOL', False)
        
        if existing_group_job and existing_group_job.group_id:
            # Add this job to the existing group
            job.group_id = existing_group_job.group_id
            logger.info(f"Created job {job.job_id} for {relative_path} - added to group {job.group_id}")
        elif existing_group_job:
            # Create a new group for both files
            group_id = str(uuid.uuid4())
            existing_group_job.group_id = group_id
            existing_group_job.is_group_primary = True
            job.group_id = group_id
            logger.info(f"Created job {job.job_id} for {relative_path} - created group {group_id} with {existing_group_job.job_id}")
        else:
            # Single file, mark as primary
            job.is_group_primary = True
            logger.info(f"Created job {job.job_id} for {relative_path} - added to queue (web_search={job.enable_web_search}, tmdb_tool={job.enable_tmdb_tool})")
        
        # Job is now in queue and will be processed by queue worker

    def _organize_file(self, job, file_path: str):
        # Safety check: don't organize if already completed
        if job.status == JobStatus.COMPLETED:
            logger.warning(f"Job {job.job_id} already completed, skipping organization")
            return
        
        library_path = self.config_manager.get('LIBRARY_PATH')
        
        logger.info(f"Organizing file for job {job.job_id}: {file_path}")
        logger.debug(f"Library path: {library_path}")
        
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
            
            # Check if destination file already exists
            if os.path.exists(destination_file):
                # Get relative path from library root to check if it's in "Other" folder
                relative_dest_path = os.path.relpath(destination_file, library_path)
                is_other_folder = relative_dest_path.startswith('Other' + os.sep) or relative_dest_path.startswith('Other/')
                
                if is_other_folder:
                    # Allow overwriting in "Other" folder
                    logger.warning(f"Destination file exists in Other folder, will overwrite: {destination_file}")
                    # Remove the existing file before moving
                    os.remove(destination_file)
                else:
                    # Fail the move for all other folders
                    error_msg = f"Destination file already exists: {destination_file}"
                    logger.error(error_msg)
                    raise FileExistsError(error_msg)
            
            shutil.move(file_path, destination_file)
            logger.info(f"Successfully moved file: {file_path} -> {destination_file}")
            # Log the successful movement
            self.file_movement_logger.log_movement(
                    source_path=file_path,
                    destination_path=destination_file,
                    job_id=job.job_id,
                    status='success'
                )
            
            self.job_store.update_job(
                job.job_id,
                JobStatus.COMPLETED,
                new_path=destination_file
            )
            logger.info(f"Job {job.job_id} marked as COMPLETED")
            
            # Trigger Jellyfin refresh if enabled
            self._trigger_jellyfin_refresh()
            
            # Clean up empty directories in downloading folder
            downloading_path = self.config_manager.get('DOWNLOADING_PATH')
            self._cleanup_empty_directories(downloading_path)
            
            # Clean up empty directories in completed folder (including subdirectories)
            completed_path = self.config_manager.get('COMPLETED_PATH')
            self._cleanup_empty_directories(completed_path)
            
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
            # Log the failed movement
            self.file_movement_logger.log_movement(
                source_path=file_path,
                destination_path=destination_file if 'destination_file' in locals() else 'unknown',
                job_id=job.job_id,
                status='failed',
                error_message=str(e)
            )
            self.job_store.update_job(
                job.job_id,
                JobStatus.FAILED,
                error_message=str(e)
            )

    def _move_uploads_to_completed(self, job):
        """Move a file from uploads folder to completed folder after AI processing."""
        try:
            uploads_path = self.config_manager.get('UPLOADS_PATH')
            completed_path = self.config_manager.get('COMPLETED_PATH')
            
            # Source file path (in uploads folder)
            source_file = os.path.join(uploads_path, job.relative_path)
            
            if not os.path.exists(source_file):
                logger.warning(f"Source file not found for job {job.job_id}: {source_file}")
                return
            
            # Destination path (in completed folder, maintaining relative path)
            dest_file = os.path.join(completed_path, job.relative_path)
            dest_dir = os.path.dirname(dest_file)
            
            # Create destination directory if needed
            os.makedirs(dest_dir, exist_ok=True)
            
            # Move the file
            shutil.move(source_file, dest_file)
            logger.info(f"Moved file from uploads to completed: {source_file} -> {dest_file}")
            
            # Update job to track that file is now in completed folder
            job.completed_file_path = dest_file
            job.original_path = dest_file
            
            # Clean up empty directories in uploads folder
            self._cleanup_empty_directories(uploads_path)
            
        except Exception as e:
            logger.error(f"Error moving file from uploads to completed for job {job.job_id}: {type(e).__name__}: {e}", exc_info=True)

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
        
        if old_config.get('UPLOADS_PATH') != new_config.get('UPLOADS_PATH'):
            new_uploads_path = new_config.get('UPLOADS_PATH')
            logger.info(f"Uploads path changed: {old_config.get('UPLOADS_PATH')} -> {new_uploads_path}")
            if self.uploads_watcher:
                self.uploads_watcher.handler.update_base_path(new_uploads_path)
                self.uploads_watcher.restart(new_uploads_path)
                logger.debug("Uploads watcher restarted with new path")

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

    def re_ai_job(self, job_id: str, custom_prompt: Optional[str] = None, include_instructions: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False):
        logger.info(f"Re-AI requested for job {job_id}")
        logger.debug(f"Custom prompt: {bool(custom_prompt)}, Include instructions: {include_instructions}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}")
        
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
            enable_web_search=enable_web_search,
            enable_tmdb_tool=enable_tmdb_tool
        )
        logger.info(f"Job {job_id} marked as QUEUED_FOR_AI with priority=True")
        
        return True

    def _check_and_remove_missing_files(self):
        """Check if files exist in downloading, uploads, or completed folders, remove jobs for missing files after 5 seconds."""
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        completed_path = self.config_manager.get('COMPLETED_PATH')
        uploads_path = self.config_manager.get('UPLOADS_PATH')
        
        # Get all jobs that are not yet completed
        active_jobs = [
            job for job in self.job_store.get_all_jobs()
            if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]
        ]
        
        for job in active_jobs:
            # Check if file exists based on source folder
            file_exists = False
            
            if job.source_folder == 'uploads':
                uploads_file_path = os.path.join(uploads_path, job.relative_path)
                file_exists = os.path.exists(uploads_file_path)
            elif job.source_folder == 'downloading':
                downloading_file_path = os.path.join(downloading_path, job.relative_path)
                file_exists = os.path.exists(downloading_file_path)
            else:
                # Check downloading folder as fallback
                downloading_file_path = os.path.join(downloading_path, job.relative_path)
                file_exists = os.path.exists(downloading_file_path)
            
            # Also check if there's a known completed file path
            if not file_exists and job.completed_file_path:
                file_exists = os.path.exists(job.completed_file_path)
            
            if not file_exists:
                # Also try completed folder with relative path
                completed_file_path = os.path.join(completed_path, job.relative_path)
                file_exists = os.path.exists(completed_file_path)
            
            if not file_exists:
                # Check if we've already noted this file as missing
                if job._missing_since is None:
                    # First time noticing it's missing, record the time
                    job._missing_since = time.time()
                    logger.debug(f"File missing for job {job.job_id}: {job.relative_path}")
                elif time.time() - job._missing_since >= 5:
                    # File has been missing for 5+ seconds, remove the job
                    logger.info(f"File has been missing for 5+ seconds, removing job {job.job_id}: {job.relative_path}")
                    self.job_store.delete_job(job.job_id)
            else:
                # File exists, clear any missing flag
                job._missing_since = None

    def _cleanup_empty_directories(self, base_path: str):
        """Remove empty directories (including subdirectories) from the specified folder."""
        try:
            # Walk the directory tree bottom-up so we can remove empty subdirectories first
            for root, dirs, files in os.walk(base_path, topdown=False):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        # Try to remove the directory (will only work if empty)
                        if not os.listdir(dir_path):
                            os.rmdir(dir_path)
                            logger.info(f"Removed empty directory: {dir_path}")
                    except OSError:
                        # Directory not empty or other error, skip
                        pass
        except Exception as e:
            logger.error(f"Error cleaning up empty directories in {base_path}: {type(e).__name__}: {e}", exc_info=True)

    def _trigger_jellyfin_refresh(self):
        """Trigger Jellyfin library refresh if enabled in config."""
        try:
            jellyfin_enabled = self.config_manager.get('JELLYFIN_REFRESH_ENABLED', False)
            
            if not jellyfin_enabled:
                logger.debug("Jellyfin refresh is disabled, skipping")
                return
            
            # Jellyfin address is hardcoded
            jellyfin_address = "http://localhost:8096"
            # Get API key from configuration
            jellyfin_api_key = self.config_manager.get('JELLYFIN_API_KEY', '')
            
            if not jellyfin_api_key:
                logger.warning("Jellyfin refresh is enabled but API key is not configured in Settings")
                return
            
            # Build the refresh URL
            refresh_url = f"{jellyfin_address}/Library/Refresh?api_key={jellyfin_api_key}"
            
            logger.info(f"Triggering Jellyfin library refresh at {jellyfin_address}")
            
            # Make the POST request
            response = requests.post(refresh_url, timeout=10)
            
            if response.status_code in [200, 204]:
                logger.info("Jellyfin library refresh triggered successfully")
            else:
                logger.warning(f"Jellyfin refresh returned status code {response.status_code}: {response.text}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error triggering Jellyfin refresh: {type(e).__name__}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error triggering Jellyfin refresh: {type(e).__name__}: {e}", exc_info=True)
