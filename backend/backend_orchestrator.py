import os
import shutil
import threading
import time
import logging
import re
import requests
import uuid
from typing import List, Optional
from pathlib import Path

from backend.job_store import JobStore, JobStatus, TV_EPISODE_PATTERN
from backend.config_manager import ConfigManager
from backend.ai_processor import AIProcessor
from backend.library_browser import LibraryBrowser
from backend.file_watcher import (
    FileWatcher, 
    DownloadingFolderHandler,
    CompletedFolderHandler
)
from backend.file_movement_logger import FileMovementLogger
from backend.ai_sse_broker import AISSEBroker
from backend.smart_agent import SmartAgent

logger = logging.getLogger(__name__)


class BackendOrchestrator:
    def __init__(self, config_manager: ConfigManager, job_store: JobStore):
        self.config_manager = config_manager
        self.job_store = job_store
        self.library_browser = LibraryBrowser(config_manager.get('LIBRARY_PATH', './test_folders/library'))
        self.ai_processor = AIProcessor(config_manager, library_browser=self.library_browser, job_store=self.job_store)
        self.smart_agent = SmartAgent(config_manager, job_store=self.job_store, library_browser=self.library_browser, ai_processor=self.ai_processor)
        self.file_movement_logger = FileMovementLogger()
        self.ai_sse_broker = AISSEBroker()
        
        self.downloading_watcher: Optional[FileWatcher] = None
        self.completed_watcher: Optional[FileWatcher] = None
        
        self.queue_thread: Optional[threading.Thread] = None
        self.queue_running = False
        
        self._running = False
        self._last_processing_time = time.time()  # Track last time we processed something
        self._stall_timeout = 30  # seconds before considering queue stalled
        self._patience_timers = {}  # batch_id -> first_seen_time for patience window
        
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
        
        loaded = self.job_store.load_pending_jobs(downloading_path, completed_path)
        if loaded > 0:
            logger.info(f"Restored {loaded} pending job(s) from disk, skipping re-scan for those files")
        
        downloading_handler = DownloadingFolderHandler(self._on_file_detected, downloading_path)
        self.downloading_watcher = FileWatcher(downloading_path, downloading_handler)
        self.downloading_watcher.start()
        logger.debug("Downloading folder watcher started")
        
        completed_handler = CompletedFolderHandler(self._on_file_in_completed, completed_path)
        self.completed_watcher = FileWatcher(completed_path, completed_handler)
        self.completed_watcher.start()
        logger.debug("Completed folder watcher started")
        
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
        # Apply default web search and TMDB tool settings from config
        job.enable_web_search = self.config_manager.get('ENABLE_WEB_SEARCH', False)
        job.enable_tmdb_tool = self.config_manager.get('ENABLE_TMDB_TOOL', False)
        job.enable_openlibrary_tool = self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False)
        job.enable_comicvine_tool = self.config_manager.get('ENABLE_COMICVINE_TOOL', False)
        
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

    def _scan_existing_files(self):
        """
        Scan downloading folder for AI processing and completed folder for direct library movement.
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
                    self._on_file_detected(file_path, relative_path)
                    downloading_count += 1
            
            if downloading_count > 0:
                logger.info(f"Found {downloading_count} existing file(s) in downloading folder")
            else:
                logger.info("No existing files found in downloading folder")
        else:
            logger.warning(f"Downloading folder does not exist: {downloading_path}")
        
        # Scan completed folder for files to move directly to library
        completed_path = self.config_manager.get('COMPLETED_PATH')
        if os.path.exists(completed_path):
            logger.info(f"Scanning for existing files in: {completed_path}")
            completed_count = 0
            
            for root, dirs, files in os.walk(completed_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, completed_path)
                    self._on_file_in_completed(file_path, relative_path)
                    completed_count += 1
            
            if completed_count > 0:
                logger.info(f"Found {completed_count} existing file(s) in completed folder")
            else:
                logger.info("No existing files found in completed folder")
        else:
            logger.warning(f"Completed folder does not exist: {completed_path}")

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

    def _smart_pre_group(self, queued_jobs: List) -> List[List]:
        """Intelligently group queued files into processing batches.
        
        Grouping strategies:
        1. TV show episodes (same show + season via SxxExx pattern)
        2. Multi-format (same base name, different extensions)
        3. Book chapters (numbered files with same prefix)
        4. Same directory + base name (existing grouping)
        
        Returns list of batches, each batch is a list of jobs.
        """
        
        # Strategy 1: Group TV episodes by show+season
        tv_groups = self._group_tv_episodes(queued_jobs)
        
        # Strategy 2: Group multi-format (same basename, diff extensions)
        multi_format_groups = self._group_multi_format(queued_jobs)
        
        # Strategy 3: Group book chapters (numbered prefix pattern)
        book_groups = self._group_book_chapters(queued_jobs)
        
        # Collect all groups
        all_batches = tv_groups + multi_format_groups + book_groups
        
        # Assign batch IDs and track which jobs are grouped
        grouped_job_ids = set()
        for batch in all_batches:
            for j in batch:
                grouped_job_ids.add(j.job_id)
        
        # Remaining ungrouped jobs get their own batch (or combine with existing batch for same dir)
        remaining = [j for j in queued_jobs if j.job_id not in grouped_job_ids]
        
        # Try to group remaining by directory + base name (existing grouping logic)
        dir_groups = {}
        for j in remaining:
            file_dir = os.path.dirname(j.relative_path)
            base_name = os.path.splitext(os.path.basename(j.relative_path))[0]
            key = f"{file_dir}/{base_name}"
            if key not in dir_groups:
                dir_groups[key] = []
            dir_groups[key].append(j)
        
        for group in dir_groups.values():
            all_batches.append(group)
        
        # Assign batch IDs
        for batch in all_batches:
            batch_id = str(uuid.uuid4())
            for job in batch:
                job.batch_id = batch_id
                job._batch_total = len(batch)
        
        return all_batches

    def _group_tv_episodes(self, queued_jobs: List) -> List[List]:
        """Group TV episode files by show name + season extracted from filename."""
        tv_groups = {}
        
        for job in queued_jobs:
            basename = os.path.splitext(os.path.basename(job.relative_path))[0]
            match = re.search(TV_EPISODE_PATTERN, basename, re.IGNORECASE)
            if not match:
                continue
            
            season = int(match.group(1))
            episode = int(match.group(2))
            
            before_ep = basename[:match.start()].strip().rstrip('.-_ ')
            # Normalize show name: lowercase, remove special chars, collapse spaces
            normalized_name = re.sub(r'[^a-z0-9]', '', before_ep.lower())
            
            key = f"{normalized_name}_s{season:02d}"
            if key not in tv_groups:
                tv_groups[key] = []
            tv_groups[key].append((episode, job))
        
        batches = []
        for key, entries in tv_groups.items():
            if len(entries) >= 1:
                entries.sort(key=lambda x: x[0])
                batch = [j for _, j in entries]
                batches.append(batch)
        
        return batches

    def _group_multi_format(self, queued_jobs: List) -> List[List]:
        """Group files with same base name but different extensions."""
        from backend.job_store import MEDIA_EXTENSIONS, SUBTITLE_EXTENSIONS, BOOK_EXTENSIONS, AUDIOBOOK_EXTENSIONS
        
        base_name_map = {}
        for job in queued_jobs:
            file_dir = os.path.dirname(job.relative_path)
            name, ext = os.path.splitext(os.path.basename(job.relative_path))
            ext = ext.lower()
            
            # Strip subtitle language codes from base name for matching
            # e.g., "movie.en" -> "movie", "movie.eng" -> "movie"
            clean_name = re.sub(r'\.(en|eng|fr|de|es|it|ja|ko|zh|ar|pt|ru|hi|nl|sv|no|da|fi|pl|cs|tr|he|th|vi|ro|hu|el|bg|uk|id|ms|tl)(\.|$)', '', name + '.')
            clean_name = clean_name.rstrip('.')
            
            key = f"{file_dir}/{clean_name}"
            if key not in base_name_map:
                base_name_map[key] = []
            base_name_map[key].append(job)
        
        batches = []
        for key, jobs in base_name_map.items():
            if len(jobs) > 1:
                batches.append(jobs)
        
        return batches

    def _group_book_chapters(self, queued_jobs: List) -> List[List]:
        """Group book chapter files by shared prefix and numeric ordering."""
        chapter_groups = {}
        
        for job in queued_jobs:
            basename = os.path.splitext(os.path.basename(job.relative_path))[0]
            prefix = os.path.dirname(job.relative_path)
            
            # Look for leading numeric prefix: "01 - Title", "01_Title", "01 Title"
            chapter_match = re.match(r'^(\d+)\s*[-._]?\s*(.*)', basename)
            if chapter_match:
                chapter_num = int(chapter_match.group(1))
                key = f"{prefix}/numbered"
                if key not in chapter_groups:
                    chapter_groups[key] = []
                chapter_groups[key].append((chapter_num, job))
                continue
            
            # Look for "Chapter_N", "Chapter N", "Chapter-N", "Part N", "Track_N"
            ch_match = re.match(r'^(chapter|part|track)\s*[-._]?\s*(\d+)', basename, re.IGNORECASE)
            if ch_match:
                ch_num = int(ch_match.group(2))
                key = f"{prefix}/named_chapter"
                if key not in chapter_groups:
                    chapter_groups[key] = []
                chapter_groups[key].append((ch_num, job))
        
        batches = []
        for key, entries in chapter_groups.items():
            if len(entries) >= 2:
                entries.sort(key=lambda x: x[0])
                batch = [j for _, j in entries]
                batches.append(batch)
        
        return batches

    def _should_process_batch(self, batch: List) -> bool:
        """Check if a batch should be processed now or wait for more files (patience window)."""
        patience_seconds = self.config_manager.get('BATCH_PATIENCE_SECONDS', 30)
        
        if patience_seconds <= 0 or len(batch) >= 10:
            return True
        
        oldest_time = min((j.created_at.timestamp() for j in batch), default=0)
        if oldest_time == 0:
            return True
        
        age = time.time() - oldest_time
        if age >= patience_seconds:
            return True
        
        logger.debug(f"Batch has {len(batch)} files, waiting for more (oldest: {age:.1f}s ago, patience: {patience_seconds}s)")
        return False
    
    def _queue_worker(self):
        """Process jobs from the queue using smart agent batching when enabled."""
        logger.info("Queue worker started")
        
        while self.queue_running:
            try:
                self._check_and_remove_missing_files()
                
                if self._check_stalled_queue():
                    logger.info("Queue was stalled, resuming processing")
                
                # First check for priority jobs (re-AI requests)
                priority_jobs = self.job_store.get_priority_jobs()
                
                if priority_jobs:
                    job = priority_jobs[0]
                    logger.info(f"Processing priority job: {job.job_id} ({job.relative_path})")
                    self._process_single_job(job, is_priority=True)
                    self._last_processing_time = time.time()
                else:
                    use_smart_agent = self.config_manager.get('ENABLE_SMART_AGENT', True)
                    
                    if use_smart_agent:
                        self._process_queue_with_agent()
                    else:
                        self._process_queue_legacy()
                
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"Error in queue worker: {type(e).__name__}: {e}", exc_info=True)
                time.sleep(1)

    def _process_queue_with_agent(self):
        """Process queued jobs using the Smart Agent with intelligent pre-grouping."""
        queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
        non_priority = [j for j in queued_jobs if not j.priority]
        
        if not non_priority:
            self._retry_failed_jobs()
            return
        
        # Smart pre-grouping
        batches = self._smart_pre_group(non_priority)
        
        if not batches:
            return
        
        # Process the first ready batch
        # For independent groups, process immediately
        # For groups waiting on patience, skip for now
        batch_found = False
        for batch in batches:
            if not batch:
                continue
            if self._should_process_batch(batch):
                logger.info(f"Smart Agent processing batch: {len(batch)} files")
                self.ai_sse_broker.publish({"type": "agent_batch_found",
                    "batch_size": len(batch),
                    "files": [j.relative_path for j in batch[:5]]})
                
                self._process_agent_batch(batch)
                self._last_processing_time = time.time()
                batch_found = True
                break
        
        # If no batch is ready (all waiting for patience), process the oldest one anyway
        if not batch_found:
            # Force process the first batch regardless of patience
            for batch in batches:
                if batch:
                    self._process_agent_batch(batch)
                    self._last_processing_time = time.time()
                    break
            else:
                # If somehow no batch, process individual jobs
                if non_priority:
                    job = non_priority[0]
                    self._process_single_job(job)

    def _process_agent_batch(self, batch: List):
        """Process a batch of jobs through the Smart Agent."""
        file_paths = [j.relative_path for j in batch]
        
        result = self.smart_agent.process_batch(
            file_paths,
            custom_prompt=getattr(batch[0], 'custom_prompt', None) if batch else None,
            on_event=self.ai_sse_broker.publish
        )
        
        logger.info(f"Smart Agent batch result: {result.get('status')} - {result.get('named')} named, {result.get('failed', 0)} failed")
        
        return result

    def _process_queue_legacy(self):
        """Original single-job-at-a-time processing for backward compatibility."""
        queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
        non_priority_jobs = [j for j in queued_jobs if not j.priority]
        
        if non_priority_jobs:
            job = non_priority_jobs[0]
            
            if job.group_id and job.is_group_primary:
                group_jobs = self.job_store.get_jobs_by_group(job.group_id)
                group_queued = [j for j in group_jobs if j.status == JobStatus.QUEUED_FOR_AI]
                
                if len(group_queued) == len(group_jobs):
                    logger.info(f"Processing grouped jobs: {len(group_jobs)} files with same base name")
                    self._process_grouped_jobs(group_jobs, is_priority=False)
                    self._last_processing_time = time.time()
                else:
                    logger.debug(f"Waiting for all files in group {job.group_id} to be ready ({len(group_queued)}/{len(group_jobs)})")
            elif job.is_group_primary or not job.group_id:
                logger.info(f"Processing queued job: {job.job_id} ({job.relative_path})")
                self._process_single_job(job, is_priority=False)
                self._last_processing_time = time.time()
            else:
                logger.debug(f"Skipping secondary file {job.job_id}, waiting for primary file in group")
        else:
            self._retry_failed_jobs()

    def _retry_failed_jobs(self):
        """Retry failed jobs after all queued jobs are processed."""
        failed_jobs = self.job_store.get_failed_jobs_for_retry()
        if failed_jobs:
            job = failed_jobs[0]
            logger.info(f"Retrying failed job: {job.job_id} ({job.relative_path}) - Attempt {job.retry_count + 1}/{job.max_retries}")
            self._process_single_job(job, is_priority=False, is_retry=True)
            self._last_processing_time = time.time()
    
    def _process_grouped_jobs(self, jobs: List, is_priority: bool = False):
        """Process a group of jobs with the same base name together through AI."""
        for job in jobs:
            self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        
        primary_job = next((j for j in jobs if j.is_group_primary), jobs[0])
        self.ai_sse_broker.publish({"type": "job_started", "job_id": primary_job.job_id, "file": f"{len(jobs)} files grouped"})
        self.ai_sse_broker.publish({"type": "thinking", "message": "Analyzing filenames..."})
        
        logger.info(f"Processing group of {len(jobs)} files together")
        
        try:
            custom_prompt = getattr(primary_job, 'custom_prompt', None)
            include_instructions = getattr(primary_job, 'include_instructions', True)
            include_filename = getattr(primary_job, 'include_filename', True)
            enable_web_search = getattr(primary_job, 'enable_web_search', self.config_manager.get('ENABLE_WEB_SEARCH', False))
            enable_tmdb_tool = getattr(primary_job, 'enable_tmdb_tool', self.config_manager.get('ENABLE_TMDB_TOOL', False))
            enable_openlibrary_tool = getattr(primary_job, 'enable_openlibrary_tool', self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False))
            enable_comicvine_tool = getattr(primary_job, 'enable_comicvine_tool', self.config_manager.get('ENABLE_COMICVINE_TOOL', False))
            enable_library_tool = getattr(primary_job, 'enable_library_tool', self.config_manager.get('ENABLE_LIBRARY_TOOL', False)) if hasattr(primary_job, 'enable_library_tool') else self.config_manager.get('ENABLE_LIBRARY_TOOL', False)
            enable_pending_tool = getattr(primary_job, 'enable_pending_tool', self.config_manager.get('ENABLE_PENDING_TOOL', False)) if hasattr(primary_job, 'enable_pending_tool') else self.config_manager.get('ENABLE_PENDING_TOOL', False)
            
            file_paths = [job.relative_path for job in jobs]
            results = self.ai_processor.process_batch(
                file_paths,
                custom_prompt=custom_prompt,
                include_default=include_instructions,
                include_filename=include_filename,
                enable_web_search=enable_web_search,
                enable_tmdb_tool=enable_tmdb_tool,
                enable_openlibrary_tool=enable_openlibrary_tool,
                enable_comicvine_tool=enable_comicvine_tool,
                enable_library_tool=enable_library_tool,
                enable_pending_tool=enable_pending_tool,
                on_event=self.ai_sse_broker.publish
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
                        suggested_name=suggested_name,
                        confidence=confidence,
                        priority=False if is_priority else job.priority
                    )
                    logger.info(f"Job {job.job_id} completed: {job.relative_path} -> {suggested_name} (confidence: {confidence}%)")
                
                logger.info(f"All grouped files will remain in downloading folder until moved to completed folder for organization")
                
                self.ai_sse_broker.publish({"type": "job_done", "job_id": primary_job.job_id, "status": "pending_completion", "confidence": primary_result.get('confidence', 0), "name": f"{len(jobs)} files processed"})
            else:
                logger.warning(f"AI results mismatch for grouped jobs: expected {len(jobs)}, got {len(results) if results else 0}")
                for job in jobs:
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.FAILED,
                        error_message="AI result mismatch for grouped files",
                        priority=False if is_priority else job.priority
                    )
                self.ai_sse_broker.publish({"type": "job_error", "job_id": primary_job.job_id, "error": "AI result mismatch for grouped files"})
        
        except Exception as e:
            logger.error(f"Error processing grouped jobs: {type(e).__name__}: {e}", exc_info=True)
            for job in jobs:
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.FAILED,
                    error_message=str(e),
                    priority=False if is_priority else job.priority
                )
            self.ai_sse_broker.publish({"type": "job_error", "job_id": primary_job.job_id, "error": str(e)[:200]})
    
    def _process_single_job(self, job, is_priority: bool = False, is_retry: bool = False):
        """Process a single job through AI."""
        self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        logger.debug(f"Updated job {job.job_id} to PROCESSING_AI status")
        
        self.ai_sse_broker.publish({"type": "job_started", "job_id": job.job_id, "file": job.relative_path})
        self.ai_sse_broker.publish({"type": "thinking", "message": "Analyzing filename..."})
        
        try:
            custom_prompt = getattr(job, 'custom_prompt', None)
            include_instructions = getattr(job, 'include_instructions', True)
            include_filename = getattr(job, 'include_filename', True)
            enable_web_search = getattr(job, 'enable_web_search', self.config_manager.get('ENABLE_WEB_SEARCH', False))
            enable_tmdb_tool = getattr(job, 'enable_tmdb_tool', self.config_manager.get('ENABLE_TMDB_TOOL', False))
            enable_openlibrary_tool = getattr(job, 'enable_openlibrary_tool', self.config_manager.get('ENABLE_OPENLIBRARY_TOOL', False))
            enable_comicvine_tool = getattr(job, 'enable_comicvine_tool', self.config_manager.get('ENABLE_COMICVINE_TOOL', False))
            enable_library_tool = getattr(job, 'enable_library_tool', self.config_manager.get('ENABLE_LIBRARY_TOOL', False)) if hasattr(job, 'enable_library_tool') else self.config_manager.get('ENABLE_LIBRARY_TOOL', False)
            enable_pending_tool = getattr(job, 'enable_pending_tool', self.config_manager.get('ENABLE_PENDING_TOOL', False)) if hasattr(job, 'enable_pending_tool') else self.config_manager.get('ENABLE_PENDING_TOOL', False)
            
            logger.debug(f"Job {job.job_id} settings: custom_prompt={bool(custom_prompt)}, include_instructions={include_instructions}, include_filename={include_filename}, web_search={enable_web_search}, tmdb_tool={enable_tmdb_tool}, openlibrary_tool={enable_openlibrary_tool}, comicvine_tool={enable_comicvine_tool}, library_tool={enable_library_tool}, pending_tool={enable_pending_tool}")
            
            result = self.ai_processor.process_single(
                job.relative_path,
                custom_prompt=custom_prompt,
                include_default=include_instructions,
                include_filename=include_filename,
                enable_web_search=enable_web_search,
                enable_tmdb_tool=enable_tmdb_tool,
                enable_openlibrary_tool=enable_openlibrary_tool,
                enable_comicvine_tool=enable_comicvine_tool,
                enable_library_tool=enable_library_tool,
                enable_pending_tool=enable_pending_tool,
                on_event=self.ai_sse_broker.publish
            )
            
            if result:
                suggested_name = result.get('suggested_name')
                confidence = result.get('confidence', 0)
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.PENDING_COMPLETION,
                    suggested_name=suggested_name,
                    confidence=confidence,
                    priority=False if is_priority else job.priority
                )
                self.ai_sse_broker.publish({"type": "job_done", "job_id": job.job_id, "status": "pending_completion", "confidence": confidence, "name": suggested_name[:80]})
                logger.info(f"Job {job.job_id} completed: {job.relative_path} -> {suggested_name} (confidence: {confidence}%)")
                logger.info(f"File will remain in downloading folder until moved to completed folder for organization")
            else:
                logger.warning(f"No AI result returned for job {job.job_id}")
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
                self.ai_sse_broker.publish({"type": "job_error", "job_id": job.job_id, "error": "No AI result returned"})
        
        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {type(e).__name__}: {e}", exc_info=True)
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
            self.ai_sse_broker.publish({"type": "job_error", "job_id": job.job_id, "error": str(e)[:200]})



    def _organize_file(self, job, file_path: str):
        # Safety check: don't organize if already completed
        if job.status == JobStatus.COMPLETED:
            logger.warning(f"Job {job.job_id} already completed, skipping organization")
            return
        
        library_path = self.config_manager.get('LIBRARY_PATH')
        
        logger.info(f"Organizing file for job {job.job_id}: {file_path}")
        logger.debug(f"Library path: {library_path}")
        
        new_name = job.suggested_name or os.path.basename(file_path)
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
                relative_dest_path = os.path.relpath(destination_file, library_path)
                is_other_folder = relative_dest_path.startswith('Other' + os.sep) or relative_dest_path.startswith('Other/')
                
                if job.force_overwrite:
                    logger.warning(f"Force overwrite enabled, removing existing file: {destination_file}")
                    os.remove(destination_file)
                elif is_other_folder:
                    logger.warning(f"Destination file exists in Other folder, will overwrite: {destination_file}")
                    os.remove(destination_file)
                else:
                    logger.warning(f"Destination file already exists: {destination_file}. Marking job as duplicate.")
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.PENDING_COMPLETION,
                        destination_exists=True
                    )
                    return
            
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

    def _on_file_in_completed(self, file_path: str, relative_path: str):
        """
        Handle files detected in completed folder - find existing job and use AI-generated path to organize.
        If no job exists with AI-generated name, skip the file.
        """
        logger.info(f"File detected in completed folder: {relative_path}")
        logger.debug(f"Full path: {file_path}")
        
        # Find existing job by matching the filename (basename)
        filename = os.path.basename(file_path)
        matching_job = None
        
        for job in self.job_store.get_all_jobs():
            # Match by basename of original_path
            job_filename = os.path.basename(job.original_path)
            if job_filename == filename:
                matching_job = job
                logger.debug(f"Found matching job {job.job_id} for file {filename}")
                break
        
        if not matching_job:
            logger.warning(f"No matching job found for file in completed folder: {filename}")
            logger.warning(f"File will not be organized. Create a job in downloading folder first.")
            return
        
        if matching_job.status != JobStatus.PENDING_COMPLETION:
            logger.warning(f"Job {matching_job.job_id} is not in PENDING_COMPLETION status (current: {matching_job.status.value})")
            logger.warning(f"File will not be organized. Job must have AI-generated name first.")
            return
        
        if not matching_job.suggested_name:
            logger.warning(f"Job {matching_job.job_id} has no AI-generated name")
            logger.warning(f"File will not be organized. Run AI processing first.")
            return
        
        # Update job's original_path to reflect new location in completed folder
        matching_job.original_path = file_path
        
        logger.info(f"Using AI-generated path from job {matching_job.job_id} to organize file")
        logger.info(f"Target: {matching_job.suggested_name}")
        
        # Use the existing _organize_file method with AI-generated path
        self._organize_file(matching_job, file_path)

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
            suggested_name=new_name,
            new_path=new_path
        )
        
        self.job_store.update_job(job_id, JobStatus.PENDING_COMPLETION)
        logger.info(f"Job {job_id} marked as PENDING_COMPLETION after manual edit")
        
        return True

    def re_ai_job(self, job_id: str, custom_prompt: Optional[str] = None, include_instructions: bool = True, include_filename: bool = True, enable_web_search: bool = False, enable_tmdb_tool: bool = False, enable_openlibrary_tool: bool = False, enable_comicvine_tool: bool = False):
        logger.info(f"Re-AI requested for job {job_id}")
        logger.debug(f"Custom prompt: {bool(custom_prompt)}, Include instructions: {include_instructions}, Include filename: {include_filename}, Web search: {enable_web_search}, TMDB tool: {enable_tmdb_tool}, OpenLibrary tool: {enable_openlibrary_tool}, ComicVine tool: {enable_comicvine_tool}")
        
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
            enable_tmdb_tool=enable_tmdb_tool,
            enable_openlibrary_tool=enable_openlibrary_tool,
            enable_comicvine_tool=enable_comicvine_tool
        )
        logger.info(f"Job {job_id} marked as QUEUED_FOR_AI with priority=True")
        
        return True

    def force_overwrite_job(self, job_id: str):
        logger.info(f"Force overwrite requested for job {job_id}")
        
        job = self.job_store.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for force overwrite")
            return False
        
        if job.status != JobStatus.PENDING_COMPLETION:
            logger.warning(f"Job {job_id} is not PENDING_COMPLETION (status: {job.status.value})")
            return False
        
        job.force_overwrite = True
        logger.info(f"Force overwrite flag set for job {job_id}")
        
        completed_path = self.config_manager.get('COMPLETED_PATH')
        file_path = os.path.join(completed_path, job.relative_path)
        
        if os.path.exists(file_path):
            logger.info(f"Attempting overwrite move for {file_path}")
            self._organize_file(job, file_path)
            return True
        else:
            logger.warning(f"File not found in completed folder: {file_path}. Overwrite will apply when file arrives.")
            return True

    def _check_and_remove_missing_files(self):
        """Check if files exist in downloading or completed folders, remove jobs for missing files after 5 seconds."""
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        completed_path = self.config_manager.get('COMPLETED_PATH')
        
        # Get all jobs that are not yet completed
        active_jobs = [
            job for job in self.job_store.get_all_jobs()
            if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.AGENT_NAMED]
        ]
        
        for job in active_jobs:
            # Check if file exists in either downloading or completed folder
            downloading_file_path = os.path.join(downloading_path, job.relative_path)
            
            # Also check if there's a known completed file path
            file_exists = os.path.exists(downloading_file_path)
            
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
