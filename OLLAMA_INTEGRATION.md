# Ollama Integration

This document describes the Ollama AI provider integration added to Intelly Jelly.

## Overview

Ollama is a local AI model server that allows you to run large language models on your own hardware. This integration adds Ollama as a third AI provider option alongside Google AI and OpenAI.

## Features

- **Local AI Processing**: Run AI models entirely on your own hardware without sending data to external services
- **Dynamic Model Discovery**: Automatically fetches available models from your Ollama server
- **Configurable Server URL**: Point to any Ollama server (local or remote)
- **Model Caching**: Model list is cached for 5 minutes to reduce unnecessary API calls

## Configuration

### Settings Location

Navigate to Settings → AI Configuration in the Intelly Jelly web interface.

### Required Settings

1. **AI Provider**: Select "Ollama (local)" from the dropdown
2. **Ollama Base URL**: Enter your Ollama server URL (default: `http://localhost:11434`)
3. **Refresh Models**: Click the "Refresh Models" button to load available models from your Ollama server
4. **AI Model**: Select a model from the dropdown

### Config.json Fields

```json
{
  "AI_PROVIDER": "ollama",
  "OLLAMA_BASE_URL": "http://localhost:11434",
  "OLLAMA_MODEL": "llama3.2",
  "AI_MODEL": "llama3.2",
  "OLLAMA_TEMPERATURE": 0.1,
  "OLLAMA_NUM_PREDICT": 2048,
  "OLLAMA_TOP_K": 40,
  "OLLAMA_TOP_P": 0.9
}
```

### Ollama Parameters

Advanced parameters to fine-tune model behavior:

- **Temperature** (0-2, default: 0.1): Controls creativity/randomness. Lower values = more deterministic, higher values = more creative
- **Max Tokens** (128-8192, default: 2048): Maximum length of the AI response
- **Top K** (1-100, default: 40): Limits token selection to the K most likely tokens
- **Top P** (0-1, default: 0.9): Nucleus sampling - cumulative probability threshold for token selection

For file organization tasks, lower temperature (0.1-0.3) is recommended for consistent naming.

## Installation & Setup

1. **Install Ollama** on your system:
   - Visit https://ollama.ai/download
   - Follow installation instructions for your OS

2. **Pull a model** (example):
   ```bash
   ollama pull llama3.2
   ollama pull mistral
   ollama pull qwen2.5
   ```

3. **Verify Ollama is running**:
   ```bash
   curl http://localhost:11434/api/tags
   ```
   This should return a JSON list of available models.

4. **Configure Intelly Jelly**:
   - Open Settings in Intelly Jelly
   - Select "Ollama (local)" as AI Provider
   - Verify the Base URL (should auto-detect `http://localhost:11434`)
   - Select a model from the dropdown
   - Save settings

## Technical Details

### API Endpoints Used

- **GET `/api/tags`**: Fetch available models from Ollama server
- **POST `/api/generate`**: Generate AI responses for file organization

### Request Format

```json
{
  "model": "llama3.2",
  "prompt": "...",
  "stream": false,
  "options": {
    "temperature": 0.1,
    "num_predict": 2048
  }
}
```

### Response Parsing

Ollama responses are parsed identically to Google AI and OpenAI responses:
- Extracts JSON from response
- Handles both array format `[{...}, {...}]` and object format `{"files": [{...}, {...}]}`
- Strips markdown code fences if present

### Limitations

- **Web Search Not Supported**: Unlike Google AI and OpenAI, Ollama does not support web search capabilities. The web search option is automatically disabled (grayed out) when Ollama is selected as the AI provider.
- **Timeout**: Requests timeout after 120 seconds (may need adjustment for slower hardware)
- **Model Performance**: Local model performance depends on your hardware. Larger models may be slower but more accurate.

## Features

### Manual Model Refresh
After entering or changing the Ollama Base URL, click the "Refresh Models" button to load available models from the server. This allows you to test connectivity and see available models before saving settings.

### Advanced Parameter Configuration
Fine-tune Ollama's behavior with configurable parameters (temperature, max tokens, top K, top P) directly in the settings interface.

### Web Search Auto-Disable
When Ollama is selected as the AI provider, the web search option is automatically disabled and grayed out in both settings and Re-AI dialogs, since local models cannot access the internet.

## Troubleshooting

### "Cannot connect to Ollama server"

1. Verify Ollama is running: `ollama list`
2. Check the base URL in settings
3. Ensure no firewall blocking port 11434
4. If using a remote server, make sure the URL is accessible (e.g., `http://192.168.1.100:11434`)
5. Check logs: `intelly_jelly.log`

### "No models available" or "Models list is empty/invisible"

1. Pull at least one model: `ollama pull llama3.2`
2. Verify models are listed: `ollama list`
3. Check that Ollama server is running: `curl http://localhost:11434/api/tags`
4. Try changing the provider to another option and back to Ollama to force refresh
5. Check browser console for JavaScript errors

### Slow performance

1. Consider using a smaller model (e.g., `llama3.2` instead of `llama3.2:70b`)
2. Increase `AI_CALL_DELAY_SECONDS` to give models more processing time
3. Check system resources (CPU/RAM/GPU usage)

### Models not loading

1. Make sure you've clicked the "Refresh Models" button after entering the URL
2. Verify the URL is accessible from your browser (e.g., `http://localhost:11434`)
3. Check browser console for errors
4. Try clicking "Refresh Models" again if the first attempt fails

## Recommended Models

For file organization tasks, these models work well:

- **llama3.2** (3B params): Fast, good for basic file naming
- **qwen2.5** (7B params): Balanced speed and accuracy
- **mistral** (7B params): Excellent for media file organization
- **llama3.1:8b**: Larger context window, better for complex naming

## Code Changes Summary

### Files Modified

1. **config.json**: Added `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TOP_K`, and `OLLAMA_TOP_P` fields
2. **backend/ai_processor.py**: 
   - Added `_process_batch_ollama()` method
   - Added `_get_ollama_models()` method for dynamic model fetching
   - Added Ollama model caching
   - Added support for configurable Ollama parameters (temperature, num_predict, top_k, top_p)
3. **app.py**: Added `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TOP_K`, and `OLLAMA_TOP_P` to allowed config fields
4. **templates/settings.html**: 
   - Added Ollama option to AI Provider dropdown
   - Added Ollama Base URL input field with "Refresh Models" button
   - Added Ollama Parameters section (temperature, max tokens, top K, top P)
   - Updated JavaScript to handle Ollama provider selection
   - Web search checkbox automatically disabled when Ollama is selected
5. **templates/index.html & library.html**:
   - Updated Re-AI modal to check AI provider and disable web search for Ollama
5. **.github/copilot-instructions.md**: Documented Ollama integration

### No Additional Dependencies

The Ollama integration uses the existing `requests` library, so no new dependencies need to be installed.
