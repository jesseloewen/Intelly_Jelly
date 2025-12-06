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

- 🤖 **AI-Powered Organization** - Understands context and finds missing metadata (Google AI, OpenAI & Ollama supported)
- 🏠 **Local AI Support** - Run completely offline with Ollama for privacy and cost savings
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
- An AI provider (choose one):
  - **Google AI** (Recommended) - Fast and accurate, requires API key
  - **OpenAI** - Reliable alternative, requires API key
  - **Ollama** (Local) - Run completely offline, no API key needed

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/JL-Bones/Intelly_Jelly.git
   cd Intelly_Jelly
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure your paths and AI provider**
   
   On first run, you'll need to configure:
   - Downloading folder path (where files are being downloaded)
   - Completed folder path (where downloads finish)
   - Library path (where organized files go)
   - AI provider and credentials (see AI Provider Setup below)

4. **Run the application**
   ```bash
   python app.py
   ```

5. **Access the web interface**
   
   Open your browser to `http://localhost:5000`

## AI Provider Setup

Intelly Jelly supports three AI providers. Choose the one that fits your needs:

### Google AI (Recommended)
- **Model**: `gemini-2.5-flash` (default, fast and accurate)
- **Pros**: Excellent accuracy, supports web search and TMDB tool
- **Cons**: Requires API key, has rate limits
- **Setup**:
  1. Get API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
  2. In Settings, ensure "Google AI" is selected as provider
  3. Enter your API key
  4. Enable web search and/or TMDB tool if desired

**Note**: `gemini-2.5-flash` with web search enabled is the most thoroughly tested configuration and provides the best results for media organization.

### OpenAI
- **Model**: `gpt-5-mini` (default, configurable)
- **Pros**: Reliable, supports TMDB tool with function calling
- **Cons**: Requires API key, costs per request, web search not supported
- **Setup**:
  1. Get API key from [OpenAI Platform](https://platform.openai.com/api-keys)
  2. In Settings, select "OpenAI" as provider
  3. Enter your API key
  4. Enable TMDB tool if desired (web search not available with OpenAI)

### Ollama (Local AI)
- **Model**: `deepseek-r1:1.5b` (default), `llama3.2`, or any compatible model
- **Pros**: Completely offline, no API costs, private, supports TMDB tool
- **Cons**: Web search not supported, requires local resources (GPU recommended)
- **Setup**:
  1. Install Ollama from [ollama.com](https://ollama.com)
  2. Pull a model: `ollama pull deepseek-r1:1.5b` (or llama3.2, mistral, etc.)
  3. Start Ollama server (usually auto-starts)
  4. In Settings:
     - Select "Ollama" as provider
     - Set base URL (default: `http://localhost:11434`)
     - Choose your model from the dropdown (dynamically fetched)
     - Enable TMDB tool if desired
  5. Web search option is automatically disabled for Ollama

**Ollama Model Selection**:
- Models are fetched from your local Ollama server dynamically
- Model list cached for 5 minutes to reduce API calls
- Recommended models for media organization:
  - `deepseek-r1:1.5b` - Fast and efficient, good for basic organization
  - `llama3.2` - Good balance of speed and accuracy
  - `llama3.1` - More accurate but slower, better for complex cases
  - `mistral` - Fast alternative with good reasoning

**Note**: Ollama models run on your local machine, so performance depends on your hardware (GPU highly recommended). TMDB tool support added for enhanced metadata lookup.

## TMDB Tool (The Movie Database)

Intelly Jelly can use The Movie Database (TMDB) API as a tool for AI to query accurate movie and TV show information. This provides more reliable metadata than web search alone.

### What the TMDB Tool Does

When enabled, the AI can call these functions:
- **Search Movie** - Get accurate movie titles, release years, and metadata
- **Search TV Show** - Get TV show titles, first air dates, and metadata  
- **Get Episode Info** - Get specific episode titles, numbers, and air dates for TV seasons

### Benefits Over Web Search

- ✅ Structured, accurate data directly from TMDB's database
- ✅ No parsing of web pages or dealing with ambiguous search results
- ✅ Episode titles and numbers for TV shows
- ✅ Works with all AI providers (Google AI, OpenAI, and Ollama)
- ✅ Complements web search - use both together for best results

### Setup

1. **Get TMDB API Key**:
   - Create account at [themoviedb.org](https://www.themoviedb.org)
   - Go to Settings → API
   - Generate a v3 API Key (free for personal use)

2. **Configure in Intelly Jelly**:
   - Open Settings page (requires admin login)
   - Find "Enable TMDB Tool" checkbox under AI Configuration
   - Check the box to enable
   - Enter your TMDB API key in the field that appears
   - Save settings

3. **How It Works**:
   - When AI encounters a movie or TV show file, it can query TMDB
   - TMDB returns accurate titles, years, and episode information
   - AI uses this data to organize files correctly
   - TMDB tool works alongside web search (both can be enabled)

**Note**: TMDB tool does NOT replace web search - they serve different purposes. TMDB is best for movie/TV metadata, while web search handles general information, music, books, etc.

## Configuration

The application can be configured through the web interface at `/settings` (requires admin login). Key settings include:

- **Folder Paths**: Downloading, completed, and library directories
- **AI Provider**: Choose between Google AI (recommended), OpenAI, or Ollama (local)
- **AI Settings**: API keys, model selection, and Ollama base URL
- **Web Search**: Enable AI to search the web for missing metadata (Google AI & OpenAI only)
- **TMDB Tool**: Enable TMDB API for accurate movie/TV show information (all providers)
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
- **intelly_jelly.log**: Application logs with DEBUG/INFO/ERROR levels (auto-rotates at 200KB/~2000 lines)
- **file_movements.json**: Structured JSON audit trail of all file movements
- **tokens.json**: Session tokens for authentication

**Log Rotation**: The main log file automatically truncates when it reaches 200KB (approximately 2000 lines) with no backup files created. This ensures logs remain manageable while preserving recent history across restarts.

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
