import os
import shutil
import threading
import time
from typing import List, Optional
from pathlib import Path

from backend.job_store import JobStore, JobStatus
from backend.config_manager import ConfigManager
from backend.ai_processor import AIProcessor
from backend.file_watcher import (
    FileWatcher, 
    DownloadingFolderHandler, 
    CompletedFolderHandler,
    DebouncedProcessor
)


class BackendOrchestrator:
    def __init__(self, config_manager: ConfigManager, job_store: JobStore):
        self.config_manager = config_manager
        self.job_store = job_store
        self.ai_processor = AIProcessor(config_manager)
        
        self.downloading_watcher: Optional[FileWatcher] = None
        self.completed_watcher: Optional[FileWatcher] = None
        self.debounced_processor: Optional[DebouncedProcessor] = None
        
        self.priority_thread: Optional[threading.Thread] = None
        self.priority_running = False
        
        self._running = False
        
        self.config_manager.register_change_callback(self._on_config_change)

    def start(self):
        if self._running:
            return
        
        self._running = True
        
        downloading_path = self.config_manager.get('DOWNLOADING_PATH')
        completed_path = self.config_manager.get('COMPLETED_PATH')
        debounce_seconds = self.config_manager.get('DEBOUNCE_SECONDS', 5)
        
        downloading_handler = DownloadingFolderHandler(self._on_file_detected)
        self.downloading_watcher = FileWatcher(downloading_path, downloading_handler)
        self.downloading_watcher.start()
        
        completed_handler = CompletedFolderHandler(self._on_file_completed)
        self.completed_watcher = FileWatcher(completed_path, completed_handler)
        self.completed_watcher.start()
        
        self.debounced_processor = DebouncedProcessor(
            debounce_seconds,
            self._process_ai_batch
        )
        
        self.priority_running = True
        self.priority_thread = threading.Thread(target=self._priority_queue_worker, daemon=True)
        self.priority_thread.start()
        
        print("Backend orchestrator started")

    def stop(self):
        if not self._running:
            return
        
        self._running = False
        self.priority_running = False
        
        if self.downloading_watcher:
            self.downloading_watcher.stop()
        
        if self.completed_watcher:
            self.completed_watcher.stop()
        
        if self.debounced_processor:
            self.debounced_processor.stop()
        
        if self.priority_thread:
            self.priority_thread.join(timeout=5)
        
        print("Backend orchestrator stopped")

    def _on_file_detected(self, file_path: str, relative_path: str):
        print(f"File detected in downloading folder: {relative_path}")
        
        existing_job = self.job_store.get_job_by_path(file_path)
        if existing_job:
            print(f"Job already exists for {relative_path}")
            return
        
        job = self.job_store.add_job(file_path, relative_path)
        print(f"Created job {job.job_id} for {relative_path}")
        
        self.debounced_processor.trigger()

    def _process_ai_batch(self):
        print("Processing AI batch...")
        
        queued_jobs = self.job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI)
        
        non_priority_jobs = [job for job in queued_jobs if not job.priority]
        
        if not non_priority_jobs:
            print("No jobs to process")
            return
        
        batch_size = self.config_manager.get('AI_BATCH_SIZE', 10)
        
        for i in range(0, len(non_priority_jobs), batch_size):
            batch = non_priority_jobs[i:i + batch_size]
            self._process_batch(batch)

    def _process_batch(self, jobs: List):
        if not jobs:
            return
        
        print(f"Processing batch of {len(jobs)} jobs")
        
        for job in jobs:
            self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
        
        file_paths = [job.relative_path for job in jobs]
        
        try:
            results = self.ai_processor.process_batch(file_paths)
            
            for job in jobs:
                matching_result = None
                for result in results:
                    if result.get('original_path') == job.relative_path:
                        matching_result = result
                        break
                
                if matching_result:
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.PENDING_COMPLETION,
                        ai_determined_name=matching_result.get('suggested_name'),
                        confidence=matching_result.get('confidence', 0)
                    )
                    print(f"Job {job.job_id}: {job.relative_path} -> {matching_result.get('suggested_name')}")
                else:
                    self.job_store.update_job(
                        job.job_id,
                        JobStatus.FAILED,
                        error_message="No AI result returned"
                    )
        
        except Exception as e:
            print(f"Error processing batch: {e}")
            for job in jobs:
                self.job_store.update_job(
                    job.job_id,
                    JobStatus.FAILED,
                    error_message=str(e)
                )

    def _priority_queue_worker(self):
        print("Priority queue worker started")
        
        while self.priority_running:
            try:
                priority_jobs = self.job_store.get_priority_jobs()
                
                if priority_jobs:
                    job = priority_jobs[0]
                    print(f"Processing priority job: {job.job_id}")
                    
                    self.job_store.update_job(job.job_id, JobStatus.PROCESSING_AI)
                    
                    try:
                        custom_prompt = job.custom_prompt
                        include_instructions = job.include_instructions
                        include_filename = job.include_filename
                        results = self.ai_processor.process_batch(
                            [job.relative_path],
                            custom_prompt=custom_prompt,
                            include_default=include_instructions,
                            include_filename=include_filename
                        )
                        
                        if results and len(results) > 0:
                            result = results[0]
                            self.job_store.update_job(
                                job.job_id,
                                JobStatus.PENDING_COMPLETION,
                                ai_determined_name=result.get('suggested_name'),
                                confidence=result.get('confidence', 0),
                                priority=False
                            )
                            print(f"Priority job {job.job_id} completed: {result.get('suggested_name')}")
                        else:
                            self.job_store.update_job(
                                job.job_id,
                                JobStatus.FAILED,
                                error_message="No AI result returned",
                                priority=False
                            )
                    
                    except Exception as e:
                        print(f"Error processing priority job: {e}")
                        self.job_store.update_job(
                            job.job_id,
                            JobStatus.FAILED,
                            error_message=str(e),
                            priority=False
                        )
                
                time.sleep(1)
            
            except Exception as e:
                print(f"Error in priority queue worker: {e}")
                time.sleep(1)

    def _on_file_completed(self, file_path: str):
        print(f"File appeared in completed folder: {file_path}")
        
        filename = os.path.basename(file_path)
        
        job = self.job_store.get_job_by_path(filename)
        
        if not job:
            for j in self.job_store.get_all_jobs():
                if os.path.basename(j.original_path) == filename:
                    job = j
                    break
        
        if not job:
            print(f"No matching job found for {filename}")
            return
        
        if job.status != JobStatus.PENDING_COMPLETION and job.status != JobStatus.MANUAL_EDIT:
            print(f"Job {job.job_id} is not ready for completion (status: {job.status.value})")
            return
        
        self._organize_file(job, file_path)

    def _organize_file(self, job, file_path: str):
        library_path = self.config_manager.get('LIBRARY_PATH')
        dry_run = self.config_manager.get('DRY_RUN_MODE', False)
        
        new_name = job.ai_determined_name or os.path.basename(file_path)
        
        if job.new_path:
            destination_dir = os.path.join(library_path, os.path.dirname(job.new_path))
            destination_file = os.path.join(library_path, job.new_path)
        else:
            destination_dir = library_path
            destination_file = os.path.join(library_path, new_name)
        
        try:
            os.makedirs(destination_dir, exist_ok=True)
            
            if os.path.exists(destination_file):
                base, ext = os.path.splitext(new_name)
                counter = 1
                while os.path.exists(destination_file):
                    new_name = f"{base}_{counter}{ext}"
                    destination_file = os.path.join(destination_dir, new_name)
                    counter += 1
            
            if dry_run:
                print(f"DRY RUN: Would move {file_path} -> {destination_file}")
            else:
                shutil.move(file_path, destination_file)
                print(f"Moved: {file_path} -> {destination_file}")
            
            self.job_store.update_job(
                job.job_id,
                JobStatus.COMPLETED,
                new_path=destination_file
            )
        
        except Exception as e:
            print(f"Error organizing file: {e}")
            self.job_store.update_job(
                job.job_id,
                JobStatus.FAILED,
                error_message=str(e)
            )

    def _on_config_change(self, old_config, new_config):
        print("Configuration changed, updating watchers...")
        
        if old_config.get('DOWNLOADING_PATH') != new_config.get('DOWNLOADING_PATH'):
            if self.downloading_watcher:
                self.downloading_watcher.restart(new_config.get('DOWNLOADING_PATH'))
        
        if old_config.get('COMPLETED_PATH') != new_config.get('COMPLETED_PATH'):
            if self.completed_watcher:
                self.completed_watcher.restart(new_config.get('COMPLETED_PATH'))
        
        if old_config.get('DEBOUNCE_SECONDS') != new_config.get('DEBOUNCE_SECONDS'):
            if self.debounced_processor:
                self.debounced_processor.update_debounce_time(new_config.get('DEBOUNCE_SECONDS', 5))

    def manual_edit_job(self, job_id: str, new_name: str, new_path: Optional[str] = None):
        job = self.job_store.get_job(job_id)
        if not job:
            return False
        
        self.job_store.update_job(
            job_id,
            JobStatus.MANUAL_EDIT,
            ai_determined_name=new_name,
            new_path=new_path
        )
        
        self.job_store.update_job(job_id, JobStatus.PENDING_COMPLETION)
        
        return True

    def re_ai_job(self, job_id: str, custom_prompt: Optional[str] = None, include_instructions: bool = True, include_filename: bool = True):
        job = self.job_store.get_job(job_id)
        if not job:
            return False
        
        self.job_store.update_job(
            job_id,
            JobStatus.QUEUED_FOR_AI,
            custom_prompt=custom_prompt,
            priority=True,
            include_instructions=include_instructions,
            include_filename=include_filename
        )
        
        return True
