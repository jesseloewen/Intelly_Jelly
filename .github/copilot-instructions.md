# Copilot Instructions for Intelly_Jelly

## Architecture Overview

Intelly_Jelly is a Flask-based AI media organizer with a threaded job queue system. The `BackendOrchestrator` is the core coordinator that:
- Runs file watchers for downloading/completed folders using `watchdog`
- Processes jobs through a single-threaded queue worker (`_queue_worker`)
- Groups related files (video+subtitle) by base filename AND directory
- Moves organized files to library and logs with `FileMovementLogger`

**Critical Flow**: File detected → Job created → Queued for AI → AI processing → Pending completion → File moved to library → Job auto-removed

## Job Lifecycle & Status Transitions

Jobs use `JobStore` (thread-safe with `RLock`) and progress through states:
- `QUEUED_FOR_AI` → `PROCESSING_AI` → `PENDING_COMPLETION` → `COMPLETED`
- Failed jobs can retry (max 3 attempts) via `get_failed_jobs_for_retry()`
- **Always use** `job_store.update_job()` rather than setting `job.status` directly
- Completed jobs auto-remove after 1 second to show final status to UI

## File Grouping Rules

Files are grouped ONLY if they have:
1. Same base filename (without extension)
2. **Same directory path** (prevents cross-folder grouping like S03E15 with S03E06)

When processing groups (`_process_grouped_jobs`):
- Primary file (`.is_group_primary = True`) determines the directory structure
- Secondary files (subtitles) have paths adjusted to match primary's directory
- All grouped files must reach `QUEUED_FOR_AI` before batch processing

## Stall Detection & Recovery

The queue worker includes automatic stall detection:
- Monitors if jobs are queued but none processing for >30 seconds
- Tracks `_last_processing_time` and resets on every successful job start
- **Important**: Failed jobs are explicitly excluded from stall detection
- Forces processing resume by prioritizing non-grouped or primary jobs

## File Movement Special Rules

**Other folder exception**: Files moving to `Other/` can overwrite existing files (uses `os.remove()` first). All other folders fail with `FileExistsError` if destination exists.

**Path resolution**: 
- AI returns full relative paths like `Movies/Title (Year)/Title (Year).mkv`
- For grouped files, secondary file paths get adjusted: extract filename → combine with primary's directory

## AI Provider Configuration

- **Google AI (recommended)**: Uses `gemini-2.5-flash` model by default
- OpenAI: Uses `gpt-5-mini` model by default
- Rate limiting: 2-second delay between API calls (configurable via `AI_CALL_DELAY_SECONDS`)
- Web search enabled per-job via `enable_web_search` flag
- AI prompt lives in `instruction_prompt.md` (authoritative rules for output format)

## Configuration Management

`ConfigManager` watches `config.json` and auto-reloads:
- Use `config_manager.register_change_callback()` for config-dependent components
- File watchers restart when `DOWNLOADING_PATH` or `COMPLETED_PATH` changes
- Priority jobs (re-AI requests) bypass queue order via `priority=True` flag

## Threading & Concurrency

- Queue worker: Single daemon thread processes one job/group at a time
- File watchers: Separate threads per folder (downloading + completed)
- File movements: Spawns daemon thread for delayed job removal
- **Never block main thread**: Use existing queue worker pattern for long operations

## Key Developer Commands

```bash
python app.py                    # Start Flask server (http://localhost:5000)
pip install -r requirements.txt  # Install dependencies
```

**Debugging tips**:
- Check `intelly_jelly.log` for orchestrator/AI call traces
- Watch `file_movements.json` for movement audit trail
- Use `test_folders/` for isolated testing (drop files in `test_folders/downloading`)
- Job status changes logged at INFO level with job_id for tracing

## Important Patterns

**Job store thread safety**: Always wrap multi-step operations in `with self._lock:` when modifying jobs

**Error handling in queue worker**: Exceptions caught and logged but worker continues (see `_queue_worker` try/except)

**Missing file cleanup**: Jobs for missing files removed after 5 seconds (tracked via `job._missing_since`)

**Empty directory cleanup**: Automatically removes empty dirs in downloading/completed folders after file movement

## API Response Parsing

AI responses must be JSON arrays with `suggested_name`, `confidence`, `original_path`. Parser handles both:
- Direct array: `[{...}, {...}]`
- Wrapped object: `{"files": [{...}, {...}]}`

## Testing & Iteration Notes

No formal tests yet. For reproducing issues:
1. Use `test_folders/downloading` for file drops
2. Check logs for orchestrator activity and AI calls
3. Verify job status transitions in dashboard
4. Test grouped file scenarios with video+subtitle pairs in same directory
