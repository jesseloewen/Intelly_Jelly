# 🍇 Intelly Jelly - Intelligent Media Organization

An advanced, automated media-organizing application with a multi-threaded Python backend and local Flask web interface.

## Features

- 🤖 **AI-Powered File Naming**: Uses OpenAI, Google Gemini, or Ollama to intelligently rename files
- 📁 **Automated Organization**: Monitors folders and automatically organizes files
- 🔄 **Batch & Priority Processing**: Efficient batch processing with priority queue for manual re-AI requests
- 🌐 **Web Interface**: Beautiful Flask-based UI for monitoring and control (port 7000)
- ⚙️ **Dynamic Configuration**: Change settings through the web UI without restarting
- 🔐 **Secure**: API keys stored separately in .env file
- 🧵 **Multi-threaded**: Efficient parallel processing with thread-safe operations

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Copy the example environment file and add your API keys:

```bash
copy .env.example .env
```

Edit `.env` and add your keys:

```
OPENAI_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
```

**Note**: If using Ollama (local), no API key is needed!

### 3. Run the Application

```bash
python main.py
```

The application will start on **http://localhost:7000**

## Configuration

All settings can be configured through the web UI at **http://localhost:7000/settings**

### Directory Paths

- **Downloading Path**: Where new files are initially detected
- **Completed Path**: Where files move after download completes
- **Library Path**: Final organized destination
- **Instructions File**: Path to AI prompt instructions

### AI Settings

- **Provider**: Choose between Ollama (local), OpenAI, or Google Gemini
- **Model**: Select from available models for your provider
- **Batch Size**: Number of files to process in each batch
- **Debounce Seconds**: Wait time before processing new files

### Advanced Options

- **Dry Run Mode**: Test without making actual AI API calls
- **Web Search**: Enable AI web search (future feature)

## How It Works

### Stage 1: Download Monitoring

1. Files appear in the `DOWNLOADING_PATH`
2. A debounce timer starts/resets for each new file
3. When timer expires, files are queued for AI processing

### Stage 2: AI Processing

1. Queued files are batched according to `AI_BATCH_SIZE`
2. Batch is sent to the configured AI provider
3. AI returns suggested names and subfolder paths
4. Jobs are marked as `PENDING_COMPLETION`

### Stage 3: File Organization

1. Files move to `COMPLETED_PATH`
2. System matches files with pending jobs
3. Files are renamed and moved to `LIBRARY_PATH`
4. Jobs are marked as `COMPLETED`

## Web Interface

### Dashboard (/)

- Real-time job monitoring with auto-refresh
- View all active jobs and their status
- Manual edit: Change filename and destination
- Re-AI: Re-process with custom instructions
- Filter jobs by status

### Settings (/settings)

- Configure all application settings
- Select AI provider and model
- Adjust processing parameters
- No restart required - changes apply immediately

## API Endpoints

The Flask server provides a REST API:

- `GET /api/jobs` - List all jobs
- `GET /api/jobs/<id>` - Get specific job
- `PUT /api/jobs/<id>` - Update job
- `POST /api/jobs/<id>/re-ai` - Re-process with AI
- `DELETE /api/jobs/<id>` - Delete job
- `GET /api/config` - Get configuration
- `POST /api/config` - Update configuration
- `GET /api/models` - Get available AI models
- `GET /api/stats` - Get job statistics

## Project Structure

```
Intelly_Jelly/
├── backend/
│   ├── config_manager.py    # Configuration management
│   ├── job_store.py          # SQLite job tracking
│   ├── file_watcher.py       # Directory monitoring
│   ├── ai_processor.py       # AI integration
│   └── file_organizer.py     # File operations
├── web/
│   ├── app.py                # Flask application
│   ├── templates/            # HTML templates
│   └── static/               # CSS & JavaScript
├── main.py                   # Application entry point
├── config.json               # User configuration
├── .env                      # API keys (create from .env.example)
├── instructions.txt          # AI prompt template
└── requirements.txt          # Python dependencies
```

## AI Providers

### Ollama (Local)

- No API key required
- Install from https://ollama.ai
- Download models: `ollama pull llama3`
- Free and private

### OpenAI

- Requires API key from https://platform.openai.com
- Supports GPT-3.5, GPT-4, and newer models
- Pay-per-use pricing

### Google Gemini

- Requires API key from https://makersuite.google.com
- Supports Gemini Pro models
- Free tier available

## Testing

Create test directories:

```bash
mkdir test_downloads test_completed test_library
```

Add test files to `test_downloads/` to see the system in action!

## Troubleshooting

### No files being processed

- Check that directories exist and are accessible
- Verify AI provider is configured correctly
- Check the dashboard for error messages

### AI errors

- Verify API keys in `.env` file
- For Ollama, ensure service is running: `ollama serve`
- Check model is available: `ollama list`

### Configuration not updating

- Settings are saved immediately
- Backend threads reload configuration automatically
- Check console for error messages

## Security Notes

- API keys are stored in `.env` and never sent to the web interface
- The web interface runs locally on port 7000
- Add `.env` to `.gitignore` (already configured)

## Contributing

This is a fully functional media organization system. Feel free to extend it with:

- Additional AI providers
- More file type support
- Advanced metadata extraction
- Web search integration
- Custom file naming rules

## License

MIT License - Use freely for personal or commercial projects

---

**Enjoy organizing your media with Intelly Jelly! 🍇**
