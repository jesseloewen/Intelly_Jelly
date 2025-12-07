from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
import threading
import os
import logging
import secrets
import hashlib
import json
from functools import wraps
from datetime import datetime, timedelta

from backend.config_manager import ConfigManager
from backend.job_store import JobStore, JobStatus
from backend.backend_orchestrator import BackendOrchestrator
from backend.ai_processor import AIProcessor
from backend.library_browser import LibraryBrowser

# Configure logging with UTF-8 encoding and rotation to keep log manageable
import sys
from logging.handlers import RotatingFileHandler

# Use RotatingFileHandler - rotates at 200KB (roughly 2000 lines), keeps no backups
file_handler = RotatingFileHandler(
    'intelly_jelly.log', 
    maxBytes=200000,  # ~2000 lines * 100 chars/line
    backupCount=0,  # No backup files - just truncate and start fresh
    encoding='utf-8'
)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.stream.reconfigure(encoding='utf-8') if hasattr(stream_handler.stream, 'reconfigure') else None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        file_handler,
        stream_handler
    ]
)

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.urandom(24)  # Generate a secret key for sessions

config_manager = ConfigManager()
job_store = JobStore()
orchestrator = BackendOrchestrator(config_manager, job_store)
ai_processor = AIProcessor(config_manager)
library_browser = LibraryBrowser(config_manager.get('LIBRARY_PATH', './test_folders/library'))

backend_thread = None

# Token storage (persisted to disk)
TOKENS_FILE = 'tokens.json'
app_tokens = {}  # {token: {password_hash: str, expires: datetime}}
admin_tokens = {}  # {token: {password_hash: str, expires: datetime}}


def load_tokens():
    """Load tokens from disk"""
    global app_tokens, admin_tokens
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, 'r') as f:
                data = json.load(f)
                # Convert ISO format strings back to datetime objects
                app_tokens = {
                    token: {
                        'password_hash': info['password_hash'],
                        'expires': datetime.fromisoformat(info['expires'])
                    }
                    for token, info in data.get('app_tokens', {}).items()
                }
                admin_tokens = {
                    token: {
                        'password_hash': info['password_hash'],
                        'expires': datetime.fromisoformat(info['expires'])
                    }
                    for token, info in data.get('admin_tokens', {}).items()
                }
                logger.info(f"Loaded {len(app_tokens)} app tokens and {len(admin_tokens)} admin tokens")
    except Exception as e:
        logger.error(f"Error loading tokens: {e}")
        app_tokens = {}
        admin_tokens = {}


def save_tokens():
    """Save tokens to disk"""
    try:
        data = {
            'app_tokens': {
                token: {
                    'password_hash': info['password_hash'],
                    'expires': info['expires'].isoformat()
                }
                for token, info in app_tokens.items()
            },
            'admin_tokens': {
                token: {
                    'password_hash': info['password_hash'],
                    'expires': info['expires'].isoformat()
                }
                for token, info in admin_tokens.items()
            }
        }
        with open(TOKENS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug("Tokens saved to disk")
    except Exception as e:
        logger.error(f"Error saving tokens: {e}")


def start_backend():
    orchestrator.start()


def generate_token():
    return secrets.token_urlsafe(32)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def validate_app_token(token):
    if token in app_tokens:
        token_data = app_tokens[token]
        if datetime.now() < token_data['expires']:
            app_password = config_manager.get('APP_PASSWORD', '')
            if hash_password(app_password) == token_data['password_hash']:
                return True
        # Token expired or password changed, remove it
        del app_tokens[token]
        save_tokens()
    return False


def validate_admin_token(token):
    if token in admin_tokens:
        token_data = admin_tokens[token]
        if datetime.now() < token_data['expires']:
            admin_password = config_manager.get('ADMIN_PASSWORD', '')
            if hash_password(admin_password) == token_data['password_hash']:
                return True
        # Token expired or password changed, remove it
        del admin_tokens[token]
        save_tokens()
    return False


def require_app_password(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        app_password = config_manager.get('APP_PASSWORD', '')
        if app_password:
            # Check session first
            if session.get('app_authenticated'):
                return f(*args, **kwargs)
            # Check cookie token
            token = request.cookies.get('app_token')
            if token and validate_app_token(token):
                session['app_authenticated'] = True
                return f(*args, **kwargs)
            return redirect(url_for('app_login'))
        return f(*args, **kwargs)
    return decorated_function


def require_admin_password(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_password = config_manager.get('ADMIN_PASSWORD', '')
        if admin_password:
            # Check session first
            if session.get('admin_authenticated'):
                return f(*args, **kwargs)
            # Check cookie token
            token = request.cookies.get('admin_token')
            if token and validate_admin_token(token):
                session['admin_authenticated'] = True
                return f(*args, **kwargs)
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/app-login', methods=['GET', 'POST'])
def app_login():
    app_password = config_manager.get('APP_PASSWORD', '')
    if not app_password:
        session['app_authenticated'] = True
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        data = request.json
        if data and data.get('password') == app_password:
            session['app_authenticated'] = True
            response_data = {'success': True}
            
            # Generate token if remember_me is requested
            if data.get('remember_me'):
                token = generate_token()
                app_tokens[token] = {
                    'password_hash': hash_password(app_password),
                    'expires': datetime.now() + timedelta(days=30)
                }
                save_tokens()
                response_data['token'] = token
            
            return jsonify(response_data)
        return jsonify({'success': False, 'error': 'Invalid password'}), 401
    
    return render_template('app_login.html')


@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    admin_password = config_manager.get('ADMIN_PASSWORD', '')
    if not admin_password:
        session['admin_authenticated'] = True
        return redirect(url_for('settings'))
    
    if request.method == 'POST':
        data = request.json
        if data and data.get('password') == admin_password:
            session['admin_authenticated'] = True
            response_data = {'success': True}
            
            # Generate token if remember_me is requested
            if data.get('remember_me'):
                token = generate_token()
                admin_tokens[token] = {
                    'password_hash': hash_password(admin_password),
                    'expires': datetime.now() + timedelta(days=30)
                }
                save_tokens()
                response_data['token'] = token
            
            return jsonify(response_data)
        return jsonify({'success': False, 'error': 'Invalid password'}), 401
    
    return render_template('admin_login.html')


@app.route('/api/validate-app-token', methods=['POST'])
def validate_app_token_endpoint():
    data = request.json
    if data and data.get('token'):
        token = data.get('token')
        if validate_app_token(token):
            session['app_authenticated'] = True
            return jsonify({'valid': True})
    return jsonify({'valid': False})


@app.route('/api/validate-admin-token', methods=['POST'])
def validate_admin_token_endpoint():
    data = request.json
    if data and data.get('token'):
        token = data.get('token')
        if validate_admin_token(token):
            session['admin_authenticated'] = True
            return jsonify({'valid': True})
    return jsonify({'valid': False})


@app.route('/logout')
def logout():
    session.pop('app_authenticated', None)
    session.pop('admin_authenticated', None)
    return redirect(url_for('index'))


@app.route('/')
@require_app_password
def index():
    return render_template('index.html')


@app.route('/settings')
@require_app_password
@require_admin_password
def settings():
    return render_template('settings.html')


@app.route('/logs')
@require_app_password
def logs():
    return render_template('logs.html')


@app.route('/library')
@require_app_password
def library():
    return render_template('library.html')


@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    jobs = job_store.get_all_jobs()
    return jsonify([job.to_dict() for job in jobs])


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job = job_store.get_job(job_id)
    if job:
        return jsonify(job.to_dict())
    return jsonify({'error': 'Job not found'}), 404


@app.route('/api/jobs/<job_id>/edit', methods=['POST'])
def edit_job(job_id):
    logger.info(f"API: Edit job request for job_id={job_id}")
    try:
        data = request.json
        new_name = data.get('new_name')
        new_path = data.get('new_path')
        logger.debug(f"Edit job data: new_name={new_name}, new_path={new_path}")
        
        if not new_name:
            logger.warning(f"Edit job request missing new_name for job_id={job_id}")
            return jsonify({'error': 'new_name is required'}), 400
        
        success = orchestrator.manual_edit_job(job_id, new_name, new_path)
        
        if success:
            logger.info(f"Job {job_id} edited successfully")
            return jsonify({'success': True, 'message': 'Job updated successfully'})
        logger.warning(f"Job {job_id} not found for edit")
        return jsonify({'error': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Error editing job {job_id}: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/jobs/<job_id>/re-ai', methods=['POST'])
def re_ai_job(job_id):
    logger.info(f"API: Re-AI job request for job_id={job_id}")
    try:
        data = request.json
        custom_prompt = data.get('custom_prompt')
        include_instructions = data.get('include_instructions', True)
        include_filename = data.get('include_filename', True)
        
        # Always use settings from config for web search and TMDB tool
        enable_web_search = config_manager.get('ENABLE_WEB_SEARCH', False)
        enable_tmdb_tool = config_manager.get('ENABLE_TMDB_TOOL', False)
        
        logger.debug(f"Re-AI job data: custom_prompt={bool(custom_prompt)}, include_instructions={include_instructions}, include_filename={include_filename}, enable_web_search={enable_web_search}, enable_tmdb_tool={enable_tmdb_tool}")
        
        success = orchestrator.re_ai_job(job_id, custom_prompt, include_instructions, include_filename, enable_web_search, enable_tmdb_tool)
        
        if success:
            logger.info(f"Job {job_id} queued for re-processing")
            return jsonify({'success': True, 'message': 'Job queued for re-processing'})
        logger.warning(f"Job {job_id} not found for re-AI")
        return jsonify({'error': 'Job not found'}), 404
    except Exception as e:
        logger.error(f"Error re-processing job {job_id}: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    logger.info(f"API: Delete job request for job_id={job_id}")
    try:
        job = job_store.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for deletion")
            return jsonify({'error': 'Job not found'}), 404
        
        # Only allow deletion of completed jobs
        if job.status != JobStatus.COMPLETED:
            logger.warning(f"Cannot delete job {job_id} - status is {job.status.value}, not Completed")
            return jsonify({'error': 'Only completed jobs can be deleted'}), 400
        
        success = job_store.delete_job(job_id)
        if success:
            logger.info(f"Job {job_id} deleted successfully")
            return jsonify({'success': True, 'message': 'Job deleted successfully'})
        
        logger.error(f"Failed to delete job {job_id}")
        return jsonify({'error': 'Failed to delete job'}), 500
    except Exception as e:
        logger.error(f"Error deleting job {job_id}: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    config = config_manager.get_all()
    return jsonify(config)


@app.route('/api/config', methods=['POST'])
@require_app_password
@require_admin_password
def update_config():
    data = request.json
    
    allowed_fields = [
        'DOWNLOADING_PATH',
        'COMPLETED_PATH',
        'LIBRARY_PATH',
        'AI_PROVIDER',
        'AI_MODEL',
        'GOOGLE_MODEL',
        'OPENAI_MODEL',
        'OLLAMA_MODEL',
        'ENABLE_WEB_SEARCH',
        'ENABLE_TMDB_TOOL',
        'AI_CALL_DELAY_SECONDS',
        'JELLYFIN_REFRESH_ENABLED',
        'APP_PASSWORD',
        'ADMIN_PASSWORD',
        'GOOGLE_API_KEY',
        'OPENAI_API_KEY',
        'TMDB_API_KEY',
        'OLLAMA_BASE_URL',
        'OLLAMA_TEMPERATURE',
        'OLLAMA_NUM_PREDICT',
        'OLLAMA_TOP_K',
        'OLLAMA_TOP_P',
        'OLLAMA_KEEP_ALIVE',
        'JELLYFIN_API_KEY'
    ]
    
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    
    success = config_manager.update_config(updates)
    
    if success:
        return jsonify({'success': True, 'message': 'Configuration updated successfully'})
    return jsonify({'error': 'Failed to update configuration'}), 500


@app.route('/api/models', methods=['POST'])
def get_models():
    data = request.json
    provider = data.get('provider')
    
    if not provider:
        return jsonify({'error': 'provider is required'}), 400
    
    try:
        models = ai_processor.get_available_models(provider)
        return jsonify({'models': models})
    except Exception as e:
        return jsonify({'models': [], 'warning': str(e)}), 200


@app.route('/api/stats', methods=['GET'])
def get_stats():
    all_jobs = job_store.get_all_jobs()
    
    stats = {
        'total': len(all_jobs),
        'queued': len([j for j in all_jobs if j.status == JobStatus.QUEUED_FOR_AI]),
        'processing': len([j for j in all_jobs if j.status == JobStatus.PROCESSING_AI]),
        'pending': len([j for j in all_jobs if j.status == JobStatus.PENDING_COMPLETION]),
        'completed': len([j for j in all_jobs if j.status == JobStatus.COMPLETED]),
        'failed': len([j for j in all_jobs if j.status == JobStatus.FAILED])
    }
    
    return jsonify(stats)


@app.route('/api/movement-logs', methods=['GET'])
def get_movement_logs():
    try:
        limit = request.args.get('limit', type=int)
        movements = orchestrator.file_movement_logger.get_all_movements(limit=limit)
        return jsonify(movements)
    except Exception as e:
        logger.error(f"Error retrieving movement logs: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve movement logs'}), 500


@app.route('/api/movement-logs/stats', methods=['GET'])
def get_movement_stats():
    try:
        stats = orchestrator.file_movement_logger.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error retrieving movement stats: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve movement stats'}), 500


@app.route('/api/library/files', methods=['GET'])
def get_library_files():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', None, type=str)
        sort_by = request.args.get('sort_by', 'modified', type=str)
        sort_order = request.args.get('sort_order', 'desc', type=str)
        current_dir = request.args.get('dir', '', type=str)
        
        # Update library path in case config changed
        library_browser.update_library_path(config_manager.get('LIBRARY_PATH'))
        
        result = library_browser.get_files_paginated(
            page=page,
            per_page=per_page,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            current_dir=current_dir
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error retrieving library files: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve library files'}), 500


@app.route('/api/library/rename', methods=['POST'])
def rename_library_file():
    logger.info("API: Rename library file request")
    try:
        data = request.json
        file_path = data.get('file_path')
        new_name = data.get('new_name')
        rename_subtitle = data.get('rename_subtitle', True)
        
        if not file_path or not new_name:
            return jsonify({'error': 'file_path and new_name are required'}), 400
        
        result = library_browser.rename_file(file_path, new_name, rename_subtitle)
        
        if result['success']:
            # Log the rename in movement logger
            for renamed in result['renamed_files']:
                orchestrator.file_movement_logger.log_movement(
                    source_path=renamed['old'],
                    destination_path=renamed['new'],
                    job_id=None,
                    status='success'
                )
            
            logger.info(f"Renamed library file(s): {file_path} -> {new_name}")
            return jsonify(result)
        else:
            logger.warning(f"Failed to rename library file: {result['message']}")
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error renaming library file: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/library/re-ai', methods=['POST'])
def re_ai_library_file():
    logger.info("API: Re-AI library file request")
    try:
        data = request.json
        file_path = data.get('file_path')
        custom_prompt = data.get('custom_prompt')
        include_instructions = data.get('include_instructions', True)
        include_filename = data.get('include_filename', True)
        enable_web_search = data.get('enable_web_search', False)
        
        if not file_path:
            return jsonify({'error': 'file_path is required'}), 400
        
        # Get just the filename for AI processing
        filename = os.path.basename(file_path)
        
        logger.debug(f"Processing library file: {filename}")
        
        # Process with AI
        result = ai_processor.process_single(
            filename,
            custom_prompt=custom_prompt,
            include_default=include_instructions,
            include_filename=include_filename,
            enable_web_search=enable_web_search
        )
        
        if result:
            logger.info(f"AI processing complete for library file: {filename}")
            return jsonify({
                'success': True,
                'suggested_name': result.get('suggested_name'),
                'confidence': result.get('confidence', 0)
            })
        else:
            logger.warning(f"No AI result returned for library file: {filename}")
            return jsonify({'error': 'No AI result returned'}), 500
            
    except Exception as e:
        logger.error(f"Error processing library file with AI: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/instruction-prompt', methods=['GET'])
@require_app_password
@require_admin_password
def get_instruction_prompt():
    """Get the current instruction prompt (custom if exists, otherwise base)"""
    logger.info("API: Get instruction prompt request")
    try:
        custom_path = 'instruction_prompt_custom.md'
        base_path = 'instruction_prompt.md'
        
        # Check if custom instructions exist
        if os.path.exists(custom_path):
            with open(custom_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return jsonify({'content': content, 'is_custom': True})
        else:
            with open(base_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return jsonify({'content': content, 'is_custom': False})
    except Exception as e:
        logger.error(f"Error reading instruction prompt: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to read instruction prompt'}), 500


@app.route('/api/instruction-prompt', methods=['POST'])
@require_app_password
@require_admin_password
def save_instruction_prompt():
    """Save custom instruction prompt"""
    logger.info("API: Save instruction prompt request")
    try:
        data = request.json
        content = data.get('content')
        
        if content is None:
            return jsonify({'error': 'content is required'}), 400
        
        custom_path = 'instruction_prompt_custom.md'
        
        # Save to custom file
        with open(custom_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Custom instruction prompt saved to {custom_path}")
        return jsonify({'success': True, 'message': 'Instructions saved successfully'})
    except Exception as e:
        logger.error(f"Error saving instruction prompt: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to save instruction prompt'}), 500


@app.route('/api/instruction-prompt/reset', methods=['POST'])
@require_app_password
@require_admin_password
def reset_instruction_prompt():
    """Reset to base instruction prompt by deleting custom file"""
    logger.info("API: Reset instruction prompt request")
    try:
        custom_path = 'instruction_prompt_custom.md'
        
        if os.path.exists(custom_path):
            os.remove(custom_path)
            logger.info(f"Deleted custom instruction prompt: {custom_path}")
        
        # Return the base instructions
        base_path = 'instruction_prompt.md'
        with open(base_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({'success': True, 'message': 'Instructions reset to default', 'content': content})
    except Exception as e:
        logger.error(f"Error resetting instruction prompt: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to reset instruction prompt'}), 500


@app.route('/api/upload', methods=['POST'])
@require_app_password
def upload_files():
    """Handle file and folder uploads to the uploads folder"""
    logger.info("API: File upload request")
    try:
        uploads_path = config_manager.get('UPLOADS_PATH')
        
        if not uploads_path:
            return jsonify({'error': 'Uploads path not configured'}), 400
        
        # Create uploads folder if it doesn't exist
        os.makedirs(uploads_path, exist_ok=True)
        
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        uploaded_count = 0
        errors = []
        
        for idx, file in enumerate(files):
            if file.filename == '':
                continue
            
            try:
                # Check if there's a relative path provided (for folder uploads)
                # Form data will have 'path_N' entries for each file in order
                relative_path = request.form.get(f'path_{idx}', file.filename)
                
                # Sanitize the path to prevent directory traversal
                relative_path = os.path.normpath(relative_path).lstrip(os.sep).lstrip('/')
                
                # Build destination path
                dest_path = os.path.join(uploads_path, relative_path)
                dest_dir = os.path.dirname(dest_path)
                
                # Create directory structure if needed
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)
                
                # Save the file
                file.save(dest_path)
                logger.info(f"Uploaded file: {relative_path}")
                uploaded_count += 1
                
            except Exception as e:
                error_msg = f"Error uploading {file.filename}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        if uploaded_count > 0:
            message = f"Successfully uploaded {uploaded_count} file(s)"
            if errors:
                message += f" with {len(errors)} error(s)"
            return jsonify({'success': True, 'message': message, 'uploaded': uploaded_count, 'errors': errors})
        else:
            return jsonify({'error': 'No files were uploaded', 'errors': errors}), 400
            
    except Exception as e:
        logger.error(f"Error handling upload: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to upload files'}), 500


if __name__ == '__main__':
    os.makedirs('./test_folders/downloading', exist_ok=True)
    os.makedirs('./test_folders/completed', exist_ok=True)
    os.makedirs('./test_folders/uploads', exist_ok=True)
    os.makedirs('./test_folders/library', exist_ok=True)
    
    # Load saved authentication tokens
    load_tokens()
    
    backend_thread = threading.Thread(target=start_backend, daemon=True)
    backend_thread.start()
    
    print("Starting Flask server on http://localhost:7000")
    app.run(host='0.0.0.0', port=7000, debug=False, threaded=True)
