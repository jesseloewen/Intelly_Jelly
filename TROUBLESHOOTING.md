# Troubleshooting Guide - Intelly Jelly

## Common Issues and Solutions

### Installation Issues

#### Problem: `pip install` fails
**Solution:**
```bash
# Update pip first
python -m pip install --upgrade pip

# Then try again
pip install -r requirements.txt
```

#### Problem: Module import errors
**Solution:**
```bash
# Make sure you're in the project directory
cd Intelly_Jelly

# Run from the project root
python main.py
```

### Configuration Issues

#### Problem: "No models available" in Settings
**Ollama:**
```bash
# Make sure Ollama is running
ollama serve

# Verify you have models installed
ollama list

# If no models, pull one
ollama pull llama3
```

**OpenAI:**
- Check that `OPENAI_API_KEY` is set in `.env`
- Verify the API key is valid
- Check your OpenAI account has credits

**Google:**
- Check that `GOOGLE_API_KEY` is set in `.env`
- Verify the API key is valid at https://makersuite.google.com

#### Problem: Configuration changes not taking effect
**Solution:**
- Settings save immediately, but check console for errors
- Backend threads reload config automatically
- If stuck, restart the application

### File Processing Issues

#### Problem: Files not being detected
**Solution:**
1. Verify directory paths in Settings
2. Make sure directories exist:
   ```bash
   mkdir test_downloads test_completed test_library
   ```
3. Check file permissions
4. Look at console output for errors

#### Problem: Files detected but not processed by AI
**Solution:**
1. Check AI provider is configured correctly
2. Verify API keys (if not using Ollama)
3. Check console for error messages
4. Try "Dry Run Mode" in Settings to test without API calls

#### Problem: Files in completed folder not being organized
**Solution:**
1. Check that a matching job exists in "Pending Completion" status
2. Verify the file name matches the job's original filename
3. Check library path exists and is writable
4. Look for errors in console

### Web Interface Issues

#### Problem: Can't access http://localhost:7000
**Solution:**
```bash
# Check if app is running
# You should see "Running on http://0.0.0.0:7000"

# If port is in use, edit web/app.py line:
# app.run(host='0.0.0.0', port=7000, debug=False)
# Change 7000 to another port like 7001
```

#### Problem: Dashboard not showing jobs
**Solution:**
1. Check browser console (F12) for JavaScript errors
2. Verify API endpoint works: http://localhost:7000/api/jobs
3. Check that jobs.db file exists
4. Try refreshing the page (F5)

#### Problem: Auto-refresh not working
**Solution:**
- Make sure "Auto-refresh" checkbox is checked
- Check browser console for errors
- Try manually clicking "Refresh" button

### API Issues

#### Problem: OpenAI API errors
**Common errors:**
- `401 Unauthorized`: Invalid API key
- `429 Too Many Requests`: Rate limit exceeded
- `500 Server Error`: OpenAI service issue

**Solutions:**
- Verify API key in `.env`
- Reduce batch size in Settings
- Wait a moment and try again
- Check OpenAI status: https://status.openai.com

#### Problem: Ollama connection errors
**Solutions:**
```bash
# Make sure Ollama is running
ollama serve

# Check it's accessible
curl http://localhost:11434/api/tags

# Verify URL in Settings matches
# Default: http://localhost:11434
```

#### Problem: Google API errors
**Solutions:**
- Verify API key at https://makersuite.google.com
- Check API is enabled in Google Cloud Console
- Review quota limits

### Database Issues

#### Problem: "Database is locked" errors
**Solution:**
- Close other processes accessing the database
- Restart the application
- If persistent, delete `jobs.db` (you'll lose job history)

#### Problem: Jobs stuck in processing
**Solution:**
1. Check console for errors
2. Use Dashboard to manually edit or delete stuck jobs
3. Restart application if needed

### Performance Issues

#### Problem: Slow processing
**Solutions:**
- Reduce batch size in Settings
- Check your internet connection (for cloud AI)
- Use Ollama locally for faster processing
- Reduce debounce time for faster detection

#### Problem: High CPU usage
**Solutions:**
- This is normal during AI processing
- Reduce batch size
- Increase debounce time to reduce frequency
- Use cloud AI instead of local Ollama

### Error Messages Explained

#### "AI provider not available"
- AI provider not configured
- API key missing or invalid
- Service not running (Ollama)

#### "No new name specified"
- AI didn't return a valid response
- Check AI instructions file
- Try "Re-AI" with custom prompt

#### "File not found"
- File was moved or deleted
- Check file permissions
- Verify paths are correct

#### "No AI result for this file"
- AI response didn't include this file
- Try processing again
- Check AI instructions format

## Debugging Tips

### Enable Verbose Logging
The console shows all activity. Watch for:
- File detection messages
- Job creation notifications
- AI processing updates
- Organization confirmations
- Error messages

### Check the Job Database
```bash
# View jobs directly
python -c "from backend.job_store import get_job_store; jobs = get_job_store().get_all_jobs(); print(f'Total jobs: {len(jobs)}'); [print(f'{j[\"original_filename\"]}: {j[\"status\"]}') for j in jobs[:10]]"
```

### Test Individual Components
```bash
# Test all modules
python test_modules.py

# Test configuration
python -c "from backend.config_manager import get_config; c = get_config(); print(c.get_all())"

# Test job store
python -c "from backend.job_store import get_job_store; s = get_job_store(); print(f'Active jobs: {len(s.get_active_jobs())}')"
```

### Clean Start
If all else fails:
```bash
# Stop the application (Ctrl+C)

# Remove database
del jobs.db

# Clear test directories
rmdir /s /q test_downloads test_completed test_library
mkdir test_downloads test_completed test_library

# Generate fresh test data
python test_generator.py

# Start fresh
python main.py
```

## Getting Help

### Check Documentation
1. README.md - Complete guide
2. QUICKSTART.md - Setup steps
3. ARCHITECTURE.md - Technical details

### Console Output
Always check the console where you ran `python main.py` for error messages and debug information.

### Browser Console
Press F12 in your browser and check the Console tab for JavaScript errors.

### Test with Dry Run Mode
Enable "Dry Run Mode" in Settings to test without making actual AI API calls.

## Still Having Issues?

### Checklist
- [ ] Python 3.10+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Configuration file exists (`config.json`)
- [ ] Directories exist and are writable
- [ ] API keys set (if using cloud AI)
- [ ] No firewall blocking localhost:7000
- [ ] Console shows no error messages

### System Requirements
- Python 3.10 or higher
- 500MB free disk space
- Internet connection (for cloud AI)
- Modern web browser

### Known Limitations
- SQLite can handle thousands of jobs, not millions
- Batch processing may be slow with large files
- Cloud AI has rate limits and costs
- Local Ollama requires good CPU/RAM

---

**Most issues are configuration-related. Double-check Settings page!**
