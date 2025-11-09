# Quick Start Guide - Intelly Jelly

## First Time Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API Keys (Optional)
If using OpenAI or Google Gemini:
```bash
# Edit .env file
notepad .env
```

Add your API keys:
```
OPENAI_API_KEY=sk-your-key-here
GOOGLE_API_KEY=your-key-here
```

**For Ollama (Local)**: No API key needed!
Just make sure Ollama is installed and running:
```bash
ollama serve
```

### 3. Generate Test Data (Optional)
```bash
python test_generator.py
```

### 4. Start the Application
```bash
python main.py
```

### 5. Open Web Interface
Open your browser to: **http://localhost:7000**

## Configuration

All settings can be changed in the web interface at:
**http://localhost:7000/settings**

### Default Configuration

- **Downloading Path**: `./test_downloads`
- **Completed Path**: `./test_completed`
- **Library Path**: `./test_library`
- **AI Provider**: Ollama (local)
- **AI Model**: llama3:latest
- **Debounce**: 5 seconds
- **Batch Size**: 10 files

## Usage

### Automatic Mode
1. Files appear in `test_downloads/`
2. After 5 seconds (debounce), they're queued for AI processing
3. AI suggests new names and subfolder paths
4. Move files to `test_completed/`
5. System automatically renames and moves to `test_library/`

### Manual Controls

From the dashboard (http://localhost:7000):

- **Edit**: Manually set filename and subfolder
- **Re-AI**: Re-process with custom instructions
- **Delete**: Remove job from tracking

## Troubleshooting

### "No models available"
- **Ollama**: Make sure `ollama serve` is running
- **OpenAI/Google**: Check API key in `.env` file

### Files not being processed
- Check directories exist and are accessible
- Verify configuration in Settings page
- Check console output for errors

### Port 7000 already in use
Stop any other services using port 7000, or edit `web/app.py` to use a different port.

## Common Workflows

### Testing with Ollama (Recommended for First Test)
1. Install Ollama from https://ollama.ai
2. Run: `ollama pull llama3`
3. Run: `ollama serve`
4. Start Intelly Jelly: `python main.py`
5. Add test files to `test_downloads/`
6. Watch magic happen! 🎉

### Production with OpenAI
1. Get API key from https://platform.openai.com
2. Add to `.env`: `OPENAI_API_KEY=sk-...`
3. In Settings, select "OpenAI" provider
4. Choose model (e.g., gpt-4)
5. Save configuration

## Features to Try

1. **Batch Processing**: Add multiple files at once
2. **Custom Prompts**: Use "Re-AI" with specific instructions
3. **Manual Override**: Edit names before moving
4. **Auto-Refresh**: Dashboard updates every 3 seconds
5. **Status Filtering**: View jobs by status

Enjoy organizing your media! 🍇
