# Intelly Jelly - Project Architecture

## Overview

Intelly Jelly is a multi-threaded Python application with Flask web interface for intelligent media file organization using AI.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Flask Web Server                         │
│                    (Port 7000)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Dashboard   │  │   Settings   │  │  REST API    │      │
│  │   (index)    │  │              │  │  Endpoints   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ├── Reads/Writes
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Configuration Layer                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  config.json (User Settings)  │  .env (API Keys)     │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ├── Used by
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                      Backend Services                        │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐ │
│  │ File Watcher   │  │ AI Processor   │  │File Organizer│ │
│  │  (Thread 1-2)  │  │ (Thread 3-4)   │  │  (Thread 5)  │ │
│  └────────────────┘  └────────────────┘  └──────────────┘ │
│           │                  │                    │         │
│           └──────────────────┼────────────────────┘         │
│                              │                              │
│                    ┌─────────▼─────────┐                   │
│                    │   Job Store       │                   │
│                    │  (SQLite DB)      │                   │
│                    └───────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ├── Monitors/Operates on
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     File System                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │ DOWNLOADING   │→ │  COMPLETED    │→ │   LIBRARY     │  │
│  │     PATH      │  │     PATH      │  │     PATH      │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ├── Provides names for
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                      AI Providers                            │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │    Ollama     │  │    OpenAI     │  │    Google     │  │
│  │    (Local)    │  │   (GPT-4)     │  │   (Gemini)    │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### Backend Services

#### 1. File Watcher (`file_watcher.py`)
- **Thread 1**: Monitors `DOWNLOADING_PATH`
- **Thread 2**: Monitors `COMPLETED_PATH`
- **Responsibilities**:
  - Detect new files
  - Implement debounce timer
  - Create jobs in Job Store
  - React to configuration changes

#### 2. AI Processor (`ai_processor.py`)
- **Thread 3**: Batch processor (periodic)
- **Thread 4**: Priority queue processor (immediate)
- **Responsibilities**:
  - Pull jobs from Job Store
  - Batch files for efficient AI processing
  - Call configured AI provider
  - Update jobs with AI responses
  - Handle priority re-processing requests

#### 3. File Organizer (`file_organizer.py`)
- **Thread 5**: Organization processor
- **Responsibilities**:
  - Find files ready to organize
  - Rename based on AI suggestions
  - Create subfolder structure
  - Move to library path
  - Mark jobs as completed

### Data Layer

#### Job Store (`job_store.py`)
- **Storage**: SQLite database (`jobs.db`)
- **Thread-Safe**: All operations use locks
- **Job States**:
  - `queued_for_ai`: Waiting for AI processing
  - `processing_ai`: Currently being processed by AI
  - `pending_completion`: Waiting for file to appear in completed path
  - `completed`: Successfully organized
  - `failed`: Error occurred

#### Configuration Manager (`config_manager.py`)
- **config.json**: User-editable settings
- **Features**:
  - Live reloading (detects file changes)
  - Callback system for change notifications
  - Thread-safe access
- **.env**: Secure API key storage
  - Never sent to web interface
  - Loaded only by backend

### Web Interface

#### Flask Application (`web/app.py`)
- **Port**: 7000
- **Pages**:
  - `/` - Main dashboard
  - `/settings` - Configuration page

#### API Endpoints
```
GET    /api/jobs              - List all jobs
GET    /api/jobs/<id>         - Get specific job
PUT    /api/jobs/<id>         - Update job
POST   /api/jobs/<id>/re-ai   - Re-process with AI
DELETE /api/jobs/<id>         - Delete job
GET    /api/config            - Get configuration
POST   /api/config            - Update configuration
GET    /api/models            - Get available AI models
GET    /api/stats             - Get statistics
```

## Data Flow

### Automatic Processing Flow

```
1. File appears in DOWNLOADING_PATH
   ↓
2. File Watcher detects it
   ↓
3. Debounce timer starts (resets on new files)
   ↓
4. Timer expires → Create job in Job Store
   ↓ (status: queued_for_ai)
   ↓
5. AI Processor picks up job in batch
   ↓
6. Send filenames to AI provider
   ↓
7. AI returns suggested names/paths
   ↓
8. Update job with AI response
   ↓ (status: pending_completion)
   ↓
9. User moves file to COMPLETED_PATH
   ↓
10. Completed Watcher detects file
    ↓
11. File Organizer processes job
    ↓
12. Rename and move to LIBRARY_PATH
    ↓ (status: completed)
    ↓
13. Job marked as complete
```

### Manual Edit Flow

```
1. User clicks "Edit" on job
   ↓
2. Sets new_name and subfolder
   ↓
3. Job status → pending_completion
   ↓
4. File appears in COMPLETED_PATH
   ↓
5. File Organizer uses manual values
   ↓
6. Organize to library
```

### Priority Re-AI Flow

```
1. User clicks "Re-AI" on job
   ↓
2. Optionally adds custom prompt
   ↓
3. Job added to Priority Queue
   ↓ (status: queued_for_ai, priority: 1)
   ↓
4. Priority Processor immediately picks up
   ↓
5. Process single job with custom prompt
   ↓
6. Update job with new AI response
```

## Thread Safety

### Synchronization Mechanisms

1. **Job Store**: `threading.RLock()` on all operations
2. **Config Manager**: `threading.RLock()` on reads/writes
3. **File Watcher**: `threading.Lock()` on pending files set
4. **Priority Queue**: `queue.Queue()` (thread-safe by design)

### Global Singletons

All major components use the singleton pattern with lazy initialization:
- `get_config()` → ConfigManager instance
- `get_job_store()` → JobStore instance
- `get_watcher_manager()` → FileWatcherManager instance
- `get_ai_processor()` → AIProcessor instance
- `get_file_organizer()` → FileOrganizer instance

## Configuration System

### Live Reloading

The ConfigManager checks for file modifications:
1. Track `config.json` modification time
2. On next access, compare timestamps
3. If changed, reload and notify callbacks
4. All backend threads receive notifications
5. Threads update their behavior

### Settings That Apply Immediately

- Directory paths (watchers restart)
- AI provider/model
- Batch size
- Debounce time
- Dry run mode

## Security

### API Key Protection

- Keys stored in `.env` file
- Loaded only by backend at startup
- Never transmitted to frontend
- Not exposed in any API endpoint
- `.env` in `.gitignore`

### Web Interface

- Runs on localhost only by default
- No authentication (local use)
- Can be configured for network access if needed

## Error Handling

### Job Failures

When errors occur:
1. Job status → `failed`
2. Error message stored in job
3. Visible in dashboard
4. User can re-process or delete

### Service Resilience

- All threads have try/catch blocks
- Errors logged to console
- Threads sleep and retry on errors
- Configuration errors don't crash system

## Testing

### Unit Testing

Run module tests:
```bash
python test_modules.py
```

### Integration Testing

1. Generate test data: `python test_generator.py`
2. Start application: `python main.py`
3. Verify in web interface: `http://localhost:7000`

### Manual Testing Workflow

1. Add files to `test_downloads/`
2. Watch jobs appear in dashboard
3. Check "Processing" status
4. Move files to `test_completed/`
5. Verify organization in `test_library/`

## Performance Considerations

### Batch Processing

- Default batch size: 10 files
- Reduces API calls
- Efficient use of AI provider
- Configurable based on provider limits

### Debounce Timer

- Default: 5 seconds
- Prevents premature processing
- Allows multiple files to batch together
- Configurable based on download speed

### Database

- SQLite for simplicity
- Adequate for thousands of jobs
- Regular cleanup of completed jobs
- Indexed queries for speed

## Future Enhancements

Potential additions:
- Web search integration for metadata
- Custom file naming rules/templates
- Duplicate file detection
- Automatic cleanup schedules
- Email/webhook notifications
- Multi-user support
- Cloud storage integration

---

**Built with**: Python 3.10+, Flask, SQLite, Watchdog, OpenAI/Google/Ollama APIs
