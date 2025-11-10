# 🍇 Intelly Jelly

**An intelligent, automated media organizer powered by AI**

Intelly Jelly is a multi-threaded Python application that watches your download folders and uses Google's Gemini AI to intelligently organize, rename, and categorize your media files. With a beautiful web interface and powerful automation, it takes the hassle out of managing your media library.

---

## ✨ Features

- **🤖 AI-Powered Organization**: Supports both Google Gemini AI and local Ollama models to intelligently determine proper file names and folder structures
- **👀 Real-Time Monitoring**: Automatically watches folders for new files and processes them in batches
- **🌐 Web Search Integration**: Optional Google Search grounding for accurate information about movies, TV shows, music, and more (Google AI only)
- **🏠 Local AI Support**: Use Ollama for completely local, offline AI processing with configurable server address
- **🎨 Beautiful Web UI**: Clean, responsive interface for monitoring jobs and managing settings
- **⚡ Priority Queue System**: Manually re-process files with custom prompts and immediate priority
- **🔧 Dynamic Configuration**: Update settings without restarting the application
- **🧵 Multi-Threaded**: Efficient concurrent processing with thread-safe operations
- **📊 Real-Time Stats**: Live job status updates and processing statistics
- **🎯 Flexible Rules**: Customizable organization rules for Movies, TV Shows, Music, Books, and more
- **🏃 Dry Run Mode**: Test organization without actually moving files
- **📝 Comprehensive Logging**: Detailed logging of all operations and API interactions

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- **AI Provider** (choose one):
  - Google AI API Key ([Get one here](https://makersuite.google.com/app/apikey))
  - **OR** Ollama running locally ([Install Ollama](https://ollama.ai/))

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/JL-Bones/Intelly_Jelly.git
   cd Intelly_Jelly
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your environment**
   
   Create a `.env` file in the root directory (if using Google AI):
   ```env
   GOOGLE_API_KEY=your_api_key_here
   ```

4. **Configure your paths and AI provider**
   
   Copy the example config and customize it:
   ```bash
   cp config.json.example config.json
   ```
   
   **For Google AI (default):**
   ```json
   {
     "DOWNLOADING_PATH": "./test_folders/downloading",
     "COMPLETED_PATH": "./test_folders/completed",
     "LIBRARY_PATH": "./test_folders/library",
     "AI_PROVIDER": "google",
     "AI_MODEL": "gemini-2.0-flash-exp",
     "ENABLE_WEB_SEARCH": true
   }
   ```
   
   **For Ollama:**
   ```json
   {
     "DOWNLOADING_PATH": "./test_folders/downloading",
     "COMPLETED_PATH": "./test_folders/completed",
     "LIBRARY_PATH": "./test_folders/library",
     "AI_PROVIDER": "ollama",
     "OLLAMA_BASE_URL": "http://localhost:11434",
     "OLLAMA_MODEL": "llama2"
   }
   ```

5. **Run the application**
   ```bash
   python app.py
   ```
   
   **Optional: Run as a System Service**
   
   To run Intelly Jelly as a background service that starts automatically on boot:
   ```bash
   sudo ./service_manager.sh setup
   sudo ./service_manager.sh enable
   sudo ./service_manager.sh start
   ```
   
   See [SERVICE_SETUP.md](SERVICE_SETUP.md) for detailed service management instructions.

6. **Open your browser**
   
   Navigate to: `http://localhost:7000`

---

## 📖 How It Works

### The Workflow

1. **Detection**: Files are detected in the `DOWNLOADING_PATH` folder
2. **Queuing**: Jobs are created and queued for AI processing
3. **AI Processing**: Gemini AI analyzes filenames and determines proper organization
4. **Pending**: Jobs wait for files to appear in `COMPLETED_PATH` folder
5. **Organization**: Files are automatically moved and renamed in `LIBRARY_PATH`

### Example

**Before:**
```
downloading/
  ├── The.Best.Movie.2024.1080p.WEB-DL.mkv
  └── awesome.show.s01e01.720p.mp4
```

**After Processing:**
```
library/
  ├── Movies/
  │   └── The Best Movie (2024)/
  │       └── The Best Movie (2024).mkv
  └── TV Shows/
      └── Awesome Show/
          └── Season 01/
              └── Awesome Show - S01E01 - Episode Title.mp4
```

---

## 🎮 Using the Web Interface

### Dashboard (`/`)

- **Job Queue**: View all active jobs and their status
- **Statistics**: Real-time counts of queued, processing, pending, completed, and failed jobs
- **Job Actions**:
  - ✏️ **Edit**: Manually edit the AI-determined name and path
  - 🔄 **Re-AI**: Re-process with custom prompts and options
  - 🗑️ **Delete**: Remove completed jobs from the list

### Settings (`/settings`)

Configure all aspects of the application:

- **Folder Paths**: Set downloading, completed, and library directories
- **AI Settings**: Choose model, enable web search, adjust batch size
- **Processing**: Configure debounce timing and dry run mode
- **Instructions**: Customize the AI organization rules

---

## ⚙️ Configuration Options

### `config.json`

| Setting | Description | Default |
|---------|-------------|---------|
| `DOWNLOADING_PATH` | Folder to watch for new files | `./test_folders/downloading` |
| `COMPLETED_PATH` | Folder where downloaded files appear | `./test_folders/completed` |
| `LIBRARY_PATH` | Destination for organized files | `./test_folders/library` |
| `INSTRUCTIONS_FILE_PATH` | Path to AI instruction file | `./instructions.md` |
| `AI_PROVIDER` | AI provider to use (`google` or `ollama`) | `google` |
| `AI_MODEL` | Google AI model name | `gemini-2.0-flash-exp` |
| `OLLAMA_BASE_URL` | Ollama server address | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | `llama2` |
| `DEBOUNCE_SECONDS` | Wait time before batch processing | `5` |
| `AI_BATCH_SIZE` | Number of files to process at once | `10` |
| `DRY_RUN_MODE` | Test without moving files | `false` |
| `ENABLE_WEB_SEARCH` | Enable Google Search grounding (Google only) | `true` |
| `AI_CALL_DELAY_SECONDS` | Delay between API calls to avoid rate limits | `2` |

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_API_KEY` | Your Google AI API key | Only when using Google AI |

---

## 📚 Media Organization Rules

Intelly Jelly follows strict naming conventions for different media types:

### 🎬 Movies
```
Movies/Movie Title (Year)/Movie Title (Year).ext
```

### 📺 TV Shows
```
TV Shows/Show Name/Season ##/Show Name - S##E## - Episode Title.ext
```

### 🎵 Music
```
Music/Artist Name/Album Name (Year)/## - Track Name.ext
```

### 📖 Books
```
Books/Author Name/Book Title (Year)/Book Title.ext
```

### 🎮 Games
```
Games/Platform/Game Title (Year)/Game Title.ext
```

For complete details, see [`instructions.md`](instructions.md) or the [File Organization Rules](Project_Wiki/06_File_Organization_Rules.md) documentation.

---

## 🔍 Web Search Feature

When enabled, Intelly Jelly uses Google's Search grounding feature to find accurate information about your media:

- **Movie Details**: Correct titles, release years, proper formatting
- **TV Show Info**: Episode names, air dates, season numbers
- **Music Metadata**: Artist names, album titles, track listings
- **Book Information**: Author names, publication years, editions

Enable web search in:
1. Global settings (`config.json` → `ENABLE_WEB_SEARCH: true`)
2. Per-job basis (Re-AI dialog → "Enable web search" checkbox)

---

## 🛠️ Advanced Usage

### Using Ollama for Local AI

Intelly Jelly supports [Ollama](https://ollama.ai/) for completely local, offline AI processing. This is perfect for:
- Privacy-conscious users who want to keep all data local
- Users without internet access or with limited bandwidth
- Those who want to avoid API costs and rate limits

**Setup Steps:**

1. **Install Ollama**
   ```bash
   # Visit https://ollama.ai/ for installation instructions
   # Or on Linux:
   curl -fsSL https://ollama.ai/install.sh | sh
   ```

2. **Pull a model**
   ```bash
   ollama pull llama2
   # Or try other models like: mistral, codellama, llama3
   ```

3. **Start Ollama** (if not already running)
   ```bash
   ollama serve
   # By default runs on http://localhost:11434
   ```

4. **Configure Intelly Jelly**
   
   Edit your `config.json`:
   ```json
   {
     "AI_PROVIDER": "ollama",
     "OLLAMA_BASE_URL": "http://localhost:11434",
     "OLLAMA_MODEL": "llama2"
   }
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

**Remote Ollama Server:**

If Ollama is running on a different machine, simply update the `OLLAMA_BASE_URL`:
```json
{
  "OLLAMA_BASE_URL": "http://192.168.1.100:11434"
}
```

### Custom Prompts

Use the Re-AI feature to process files with custom instructions:

```
This is a Japanese anime movie from Studio Ghibli.
Use the original Japanese title with English subtitle in parentheses.
```

### Manual Editing

Override AI suggestions by clicking "Edit" on any job:
- Change the destination filename
- Specify a custom folder path
- Correct any mistakes

### Priority Processing

Re-AI requests are processed immediately, bypassing the batch queue for instant results.

---

## 📊 API Endpoints

Intelly Jelly provides a RESTful API for integration:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/jobs` | Get all jobs |
| `GET` | `/api/jobs/<id>` | Get specific job |
| `POST` | `/api/jobs/<id>/edit` | Edit job name/path |
| `POST` | `/api/jobs/<id>/re-ai` | Re-process with AI |
| `DELETE` | `/api/jobs/<id>` | Delete completed job |
| `GET` | `/api/config` | Get configuration |
| `POST` | `/api/config` | Update configuration |
| `POST` | `/api/models` | Get available AI models |
| `GET` | `/api/stats` | Get processing statistics |

---

## 📖 Documentation

For in-depth technical documentation, see the [Project Wiki](Project_Wiki/):

- [Architecture Overview](Project_Wiki/01_Architecture_Overview.md)
- [Backend Components](Project_Wiki/02_Backend_Components.md)
- [Frontend Interface](Project_Wiki/03_Frontend_Interface.md)
- [Configuration Guide](Project_Wiki/04_Configuration_Guide.md)
- [Processing Workflows](Project_Wiki/05_Processing_Workflows.md)
- [File Organization Rules](Project_Wiki/06_File_Organization_Rules.md)
- [Development Guide](Project_Wiki/07_Development_Guide.md)

---

## 🐛 Troubleshooting

### Jobs Stuck in "Processing"

- Check `intelly_jelly.log` for error messages
- Verify your Google API key is valid
- Ensure the AI model supports your request

### Files Not Moving

- Confirm files are in the `COMPLETED_PATH` folder
- Check file permissions
- Enable dry run mode to test without moving files

### Web Search Not Working

- Ensure `ENABLE_WEB_SEARCH` is `true` in config
- Verify you're using a compatible Gemini model (2.0+ recommended)
- Check API logs for any grounding errors

### API Rate Limits

- Reduce `AI_BATCH_SIZE` in settings
- Increase `DEBOUNCE_SECONDS` to process less frequently
- Monitor the logs for 429 errors

---

## 🧪 Development

### Running Tests

```bash
python test_functionality.py
```

### Logging

Logs are written to:
- Console (stdout)
- `intelly_jelly.log` file

Detailed API request/response logging is included for debugging.

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## 📜 License

This project is provided as-is for personal use. See repository for license details.

---

## 🙏 Acknowledgments

- **Google Gemini AI**: For powerful language understanding and generation
- **Ollama**: For making local AI accessible and easy to use
- **Flask**: For the lightweight web framework
- **Watchdog**: For reliable file system monitoring
- **Contributors**: Thanks to everyone who has contributed to this project

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/JL-Bones/Intelly_Jelly/issues)
- **Documentation**: [Project Wiki](Project_Wiki/)
- **Logs**: Check `intelly_jelly.log` for detailed information

---

## 🗺️ Roadmap

- [x] Support for Ollama (local AI)
- [ ] Support for additional AI providers (OpenAI, Anthropic)
- [ ] Automatic metadata fetching and tagging
- [ ] Integration with media servers (Plex, Jellyfin)
- [ ] Mobile app for remote monitoring
- [ ] Advanced filtering and search
- [ ] Scheduled processing windows
- [ ] Webhook notifications

---

**Made with ❤️ and AI**
