# Copilot Instructions for Intelly_Jelly

## Architecture Overview

Intelly_Jelly is a Flask-based AI media organizer with a threaded job queue system. The `BackendOrchestrator` is the core coordinator that:
- Runs file watchers for downloading and completed folders using `watchdog`
- Processes jobs through a single-threaded queue worker (`_queue_worker`)
- Groups related files (video+subtitle) by base filename AND directory
- Moves organized files to library and logs with `FileMovementLogger`

**Critical Flows**:
- **Downloading folder**: File detected → Job created → AI processes and generates name/path → Job status = PENDING_COMPLETION → **File stays in downloading folder**
- **Completed folder**: File detected → Finds matching job by filename → Uses AI-generated path → Moves to library → Job marked COMPLETED

**Important**: Files in downloading folder are NEVER moved by this script. External tools (like download clients) move files from downloading to completed when ready. Only then are they organized to the library using the AI-generated path.

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

## AI Provider Configuration

### Three Provider Support
- **Google AI**: `gemini-2.5-flash` - Supports web search & TMDB, multi-turn function calling
- **OpenAI**: `gpt-5-mini` - TMDB only (web search not supported), multi-turn function calling via `chat.completions`
- **Ollama**: Local models - TMDB only (web search not supported), function calling via OpenAI-compatible format

### Critical Implementation Details

**OpenAI API Selection**: Code automatically switches between APIs based on tools:
- With tools (TMDB): Uses `chat.completions.create()` with multi-turn conversation for function calling
- Without tools: Uses `responses.create()` for simpler, faster responses
- Web search logs warning when requested (not supported by standard OpenAI API)

**Multi-Turn Function Calling**: All providers support TMDB function execution:
- Google AI: Native `function_declarations` format with tool execution loop
- OpenAI/Ollama: OpenAI-compatible `tools` array with `tool_calls` response handling
- Max 5 conversation turns to execute functions and get final answer
- Functions: `search_movie`, `search_tv_show`, `get_tv_episode_info`

**Settings-Driven Configuration**: 
- `ENABLE_WEB_SEARCH` and `ENABLE_TMDB_TOOL` in `config.json` control tool availability
- Auto AI: Jobs inherit settings from config when created (`job.enable_web_search`, `job.enable_tmdb_tool`)
- Re-AI: Always uses current config settings, ignores any client-sent values
- Rate limiting: 2-second delay between API calls (configurable via `AI_CALL_DELAY_SECONDS`)

## TMDB Tool Integration

Located in `backend/tmdb_api.py`, the `TMDBClient` provides three functions as AI tools:
- **search_movie**: Query movies by title, returns name/year/overview
- **search_tv_show**: Query TV shows by title, returns name/first_air_date/overview
- **get_tv_episode_info**: Get episode details for season/episode numbers

Tool definitions differ by provider:
- Google AI: `function_declarations` in tools array (see `_get_tmdb_tool_definition_google`)
- OpenAI/Ollama: `tools` array with `type: "function"` (see `_get_tmdb_tools_for_openai`)

Function execution: `_execute_tmdb_function()` in `ai_processor.py` handles all three functions

## Configuration Management

`ConfigManager` watches `config.json` and auto-reloads:
- Use `config_manager.register_change_callback()` for config-dependent components
- File watchers restart when `DOWNLOADING_PATH` or `COMPLETED_PATH` changes
- Settings UI checkboxes: Explicitly set values (checked/unchecked) - unchecked boxes don't appear in FormData
- Priority jobs (re-AI requests) bypass queue order via `priority=True` flag

## Threading & Concurrency

- Queue worker: Single daemon thread processes one job/group at a time
- File watchers: Separate threads per folder (downloading + completed)
- File movements: Spawns daemon thread for delayed job removal
- **Never block main thread**: Use existing queue worker pattern for long operations

## Logging System

**Line-Based Log Rotation** (`app.py` lines 16-34):
- Uses `RotatingFileHandler` with `maxBytes=200000` (~2000 lines)
- `backupCount=0` means no backup files - truncates and starts fresh when full
- Always logs to `intelly_jelly.log` across restarts
- Logs to both file and stdout (stream handler)

## Key Developer Commands

```bash
python app.py                    # Start Flask server (http://localhost:5000)
sudo systemctl restart intelly-jelly.service  # Restart production service
pip install -r requirements.txt  # Install dependencies
```

**Debugging tips**:
- Check `intelly_jelly.log` for orchestrator/AI call traces (auto-truncates at 200KB)
- Watch `file_movements.json` for movement audit trail
- Use `test_folders/` for isolated testing (drop files in `test_folders/downloading`)
- Job status changes logged at INFO level with job_id for tracing
- OpenAI requests log full prompt/response and tool calls at INFO level

## Important Patterns

**Job store thread safety**: Always wrap multi-step operations in `with self._lock:` when modifying jobs

**Settings UI checkboxes**: Must explicitly read `.checked` state and set in config object - FormData omits unchecked boxes

**Error handling in queue worker**: Exceptions caught and logged but worker continues (see `_queue_worker` try/except)

**Missing file cleanup**: Jobs for missing files removed after 5 seconds (tracked via `job._missing_since`)

**Empty directory cleanup**: Automatically removes empty dirs in downloading/completed folders after file movement

**Other folder overwrite exception**: Files moving to `Other/` can overwrite (uses `os.remove()` first), all other folders fail with `FileExistsError`

## API Response Parsing

AI responses must be JSON arrays with `suggested_name`, `confidence`, `original_path`. Parser handles both:
- Direct array: `[{...}, {...}]`
- Wrapped object: `{"files": [{...}, {...}]}`

## Testing & Iteration

No formal tests yet. For reproducing issues:
1. Use `test_folders/downloading` for file drops
2. Check logs for orchestrator activity and AI calls
3. Verify job status transitions in dashboard
4. Test grouped file scenarios with video+subtitle pairs in same directory
5. Test TMDB function calling by enabling tool and processing movie/TV files
