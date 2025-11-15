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

- 🤖 **AI-Powered Organization** - Understands context and finds missing metadata
- 👀 **Real-Time Monitoring** - Watches folders for new files automatically
- 🎬 **Media-Specific Rules** - Different organization patterns for movies, TV shows, music, books, and software
- 🌐 **Web-Based Dashboard** - Monitor jobs, browse your library, view logs, and configure settings
- 🔐 **Authentication** - Separate app and admin login with token-based auth
- 📊 **Job Queue System** - Track processing status, confidence scores, and history
- 🎨 **Theme Support** - Multiple UI themes available

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
- **AI Settings**: API endpoint and authentication key
- **Auto-Processing**: Enable/disable automatic file organization
- **Passwords**: Set app and admin passwords

Configuration is stored in `config.json` and persists between sessions.

## How It Works

1. **File Detection**: Watchdog monitors configured folders for new files
2. **Job Creation**: New files are added to the processing queue
3. **AI Analysis**: Files are sent to AI with detailed organization instructions
4. **Metadata Research**: AI searches the web for missing information (year, episode numbers, etc.)
5. **Path Suggestion**: AI returns properly formatted destination paths with confidence scores
6. **Review & Approval**: Jobs can be reviewed in the dashboard before execution
7. **File Movement**: Approved jobs move files to the library with proper structure
8. **Logging**: All operations are logged for audit purposes

## Organization Rules

The AI follows strict rules defined in `instruction_prompt.md`:

- **Movies**: `Movies/Movie Title (Year)/Movie Title (Year).ext`
- **TV Shows**: `TV Shows/Show Name (Year)/Season XX/Show Name - SXXEXX - Episode Title.ext`
- **Music**: `Music/Artist/Album/Track Number - Track Title.ext`
- **Books**: `Books/Author/Book Title (Year).ext`
- **Software**: Preserves original structure
- **Other**: Everything else goes to `Other/`

Subtitles, extras, and special features are handled according to media server conventions.

## API Endpoints

- `POST /api/start` - Start the backend orchestrator
- `POST /api/stop` - Stop the backend orchestrator
- `GET /api/jobs` - Get all jobs with optional status filter
- `POST /api/process-job/<job_id>` - Process a specific job
- `POST /api/approve-job/<job_id>` - Approve and execute a job
- `DELETE /api/reject-job/<job_id>` - Reject and remove a job
- `GET /api/library` - Browse library contents
- `GET /api/logs` - Get file movement logs
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration

## Security

- Token-based authentication for app and admin access
- Session management with secure cookies
- Separate admin privileges for configuration changes
- Password hashing for credential storage

## Logging

All file operations are logged to:
- Console output
- `intelly_jelly.log` - Application logs
- `file_movements.log` - File movement audit trail

## Contributing

This project was entirely vibe coded, so contributions that maintain the vibe are welcome! Feel free to submit issues or pull requests.

## License

MIT License - Do whatever you want with it!

---

*Built with vibes, powered by AI* 🎵✨
