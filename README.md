# Intelly Jelly 🍇

> An AI-powered media library organizer that automatically categorizes and renames your files with proper structure. Built entirely through vibe coding.

## What It Does

Intelly Jelly watches your download folders and uses AI to intelligently organize your media files (movies, TV shows, music, books) into a properly structured library. It automatically:

- **Detects** new files in your downloading/completed folders
- **Analyzes** file names and contents using AI
- **Researches** missing information (release years, episode numbers, etc.) via web search
- **Renames** files according to media library best practices (Plex/Jellyfin compatible)
- **Organizes** files into the correct folder structure
- **Logs** all file movements for tracking

## Features

- 🤖 **AI-Powered Organization** - Understands context and finds missing metadata (Google AI & OpenAI supported)
- 👀 **Real-Time Monitoring** - Watches folders for new files automatically with intelligent grouping
- 🎬 **Media-Specific Rules** - Different organization patterns for movies, TV shows, music, books, and software
- 🌐 **Web-Based Dashboard** - Monitor jobs, browse your library, view logs, and configure settings
- 🔐 **Authentication** - Separate app and admin login with token-based auth
- 📊 **Job Queue System** - Single-threaded queue with automatic stall detection and recovery
- 🎨 **Theme Support** - Multiple UI themes (light/dark)
- 📦 **Smart File Grouping** - Automatically groups related files (video + subtitle) by directory
- 🔄 **Auto-Retry Logic** - Failed jobs automatically retry up to 3 times
- 🛡️ **Overwrite Protection** - Prevents accidental overwrites except in "Other" folder

## Project Structure

```
Intelly_Jelly/
├── app.py                      # Flask web application & API
├── requirements.txt            # Python dependencies
├── instruction_prompt.md       # AI prompt instructions for file organization
├── backend/
│   ├── ai_processor.py         # AI API integration for file analysis
│   ├── backend_orchestrator.py # Main orchestrator coordinating all components
│   ├── config_manager.py       # Configuration management
│   ├── file_movement_logger.py # Logs all file operations
│   ├── file_watcher.py         # Monitors folders for new files
│   ├── job_store.py            # Job queue and status tracking
│   └── library_browser.py      # Library browsing functionality
├── static/
│   └── themes.css              # UI themes
└── templates/
    ├── index.html              # Dashboard
    ├── library.html            # Library browser
    ├── logs.html               # File movement logs
    ├── settings.html           # Configuration page
    ├── admin_login.html        # Admin authentication
    └── app_login.html          # User authentication
```

## Installation

### Prerequisites

- Python 3.8+
- An AI API endpoint (configured in settings)

### Setup

1. **Clone the repository**
   ```powershell
   git clone https://github.com/JL-Bones/Intelly_Jelly.git
   cd Intelly_Jelly
   ```

2. **Install dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure your paths**
   
   On first run, you'll need to configure:
   - Downloading folder path (where files are being downloaded)
   - Completed folder path (where downloads finish)
   - Library path (where organized files go)
   - AI API endpoint and key

4. **Run the application**
   ```powershell
   python app.py
   ```

5. **Access the web interface**
   
   Open your browser to `http://localhost:5000`

## Configuration

The application can be configured through the web interface at `/settings` (requires admin login). Key settings include:

- **Folder Paths**: Downloading, completed, and library directories
- **AI Provider**: Choose between Google AI (recommended) or OpenAI
- **AI Settings**: API keys and model selection
- **Web Search**: Enable AI to search the web for missing metadata
- **Auto-Processing**: Enable/disable automatic file organization
- **Passwords**: Set app and admin passwords
- **Jellyfin Integration**: Optional library refresh triggers

Configuration is stored in `config.json` and auto-reloads without restart.

## How It Works

1. **File Detection**: Watchdog monitors configured folders for new files recursively
2. **Smart Grouping**: Related files (video + subtitle) are grouped by base name AND directory
3. **Job Creation**: New files are added to the thread-safe processing queue
4. **AI Analysis**: Files are sent to AI with detailed organization instructions from `instruction_prompt.md`
5. **Metadata Research**: AI searches the web for missing information (year, episode numbers, etc.)
6. **Path Suggestion**: AI returns properly formatted destination paths with confidence scores
7. **Directory Sync**: Grouped files are automatically placed in the same subfolder
8. **Review & Approval**: Jobs can be reviewed in the dashboard before execution
9. **File Movement**: Approved jobs move files to the library with proper structure
10. **Auto-Cleanup**: Empty directories are automatically removed, completed jobs are purged
11. **Logging**: All operations are logged to `intelly_jelly.log` and `file_movements.json`

## Organization Rules

The AI follows strict rules defined in `instruction_prompt.md`:

- **Movies**: `Movies/Movie Title (Year)/Movie Title (Year).ext`
- **TV Shows**: `TV Shows/Show Name (Year)/Season XX/Show Name - SXXEXX - Episode Title.ext`
- **Music**: `Music/Artist/Album/Track Number - Track Title.ext`
- **Books**: `Books/Author/Book Title (Year).ext`
- **Software**: Preserves original structure
- **Other**: Everything else goes to `Other/`

Subtitles, extras, and special features are handled according to media server conventions.

## Advanced Features

### Queue Management
- **Single-threaded processing**: Jobs processed one at a time for reliability
- **Stall detection**: Automatically recovers if queue stops processing (30s timeout)
- **Priority processing**: Re-AI requests bypass queue order
- **Failed job retry**: Automatic retry with exponential backoff (max 3 attempts)

### File Handling
- **Smart grouping**: Groups files by base name AND directory to prevent cross-folder conflicts
- **Overwrite protection**: Blocks overwrites in organized folders, allows in "Other"
- **Missing file cleanup**: Auto-removes jobs for missing files after 5 seconds
- **Path adjustment**: Secondary files (subtitles) automatically use primary file's directory

### Logging & Monitoring
- **Movement audit trail**: `file_movements.json` tracks all file operations
- **Job lifecycle tracking**: Every status change logged with job_id
- **Real-time dashboard**: Updates every 3 seconds with job status
- **Library browser**: Paginated view with search, sort, and rename functionality

## API Endpoints

### Job Management
- `POST /api/start` - Start the backend orchestrator
- `POST /api/stop` - Stop the backend orchestrator
- `GET /api/jobs` - Get all jobs with optional status filter
- `POST /api/process-job/<job_id>` - Process a specific job
- `POST /api/approve-job/<job_id>` - Approve and execute a job
- `DELETE /api/reject-job/<job_id>` - Reject and remove a job
- `POST /api/jobs/<job_id>/edit` - Manually edit job destination
- `POST /api/jobs/<job_id>/re-ai` - Re-process job with AI

### Library & Logs
- `GET /api/library/files` - Browse library with pagination
- `POST /api/library/rename` - Rename files in library
- `POST /api/library/re-ai` - Re-process library file with AI
- `GET /api/movement-logs` - Get file movement history
- `GET /api/movement-logs/stats` - Get movement statistics

### Configuration
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration (requires admin)
- `GET /api/stats` - Get job queue statistics

## Security

- Token-based authentication for app and admin access
- Session management with secure cookies
- Separate admin privileges for configuration changes
- Password hashing for credential storage

## Logging

All operations are logged for debugging and audit purposes:
- **Console output**: Real-time status updates
- **intelly_jelly.log**: Application logs with DEBUG/INFO/ERROR levels
- **file_movements.json**: Structured JSON audit trail of all file movements
- **tokens.json**: Session tokens for authentication

## Troubleshooting

### Queue appears stuck
- The system has automatic stall detection (30s timeout)
- Check `intelly_jelly.log` for error messages
- Verify AI API credentials in Settings
- Restart the orchestrator via the dashboard

### Files not grouping correctly
- Files must be in the same directory to group
- Files must have the same base filename (without extension)
- Check logs for "Group directory structure" messages

### File movement fails
- Check that destination file doesn't already exist (except in "Other" folder)
- Verify library path is writable
- Review `file_movements.json` for error details

### Testing & Development
- Use `test_folders/downloading` for safe testing
- Drop test files there to trigger processing
- Monitor logs for orchestrator activity
- Check dashboard for job status transitions

## Contributing

This project was entirely **vibe coded** 🎵, so contributions that maintain the vibe are welcome! 

- See `.github/copilot-instructions.md` for architecture details
- Follow existing patterns for threading and job management
- Test with `test_folders/` before production changes
- Feel free to submit issues or pull requests

## License

MIT License - Do whatever you want with it!

---

*Built with vibes, powered by AI* 🎵✨
