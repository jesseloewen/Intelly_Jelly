"""
Flask Application
Main web interface for Intelly Jelly.
"""

from flask import Flask, render_template, jsonify, request
from pathlib import Path

from backend.config_manager import get_config
from backend.job_store import get_job_store, JobStatus
from backend.ai_processor import get_ai_processor
from backend.file_organizer import get_file_organizer


app = Flask(__name__)


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')


@app.route('/settings')
def settings():
    """Settings configuration page."""
    return render_template('settings.html')


# API Endpoints

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Get all active jobs."""
    job_store = get_job_store()
    
    # Get filter parameters
    status_filter = request.args.get('status')
    limit = int(request.args.get('limit', 1000))
    
    if status_filter:
        jobs = job_store.get_jobs_by_status(status_filter)
    else:
        jobs = job_store.get_all_jobs(limit=limit)
    
    return jsonify({'jobs': jobs})


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get a specific job."""
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    
    if job:
        return jsonify(job)
    else:
        return jsonify({'error': 'Job not found'}), 404


@app.route('/api/jobs/<job_id>', methods=['PUT'])
def update_job(job_id):
    """Update a job."""
    job_store = get_job_store()
    data = request.json
    
    # Validate required fields for manual edit
    if 'new_name' in data or 'subfolder' in data:
        updates = {}
        if 'new_name' in data:
            updates['new_name'] = data['new_name']
        if 'subfolder' in data:
            updates['subfolder'] = data['subfolder']
        
        # Set status to pending completion if provided values
        if updates:
            updates['status'] = JobStatus.PENDING_COMPLETION
            success = job_store.update_job(job_id, updates)
            
            if success:
                return jsonify({'success': True, 'message': 'Job updated'})
            else:
                return jsonify({'error': 'Job not found'}), 404
    
    return jsonify({'error': 'Invalid update data'}), 400


@app.route('/api/jobs/<job_id>/re-ai', methods=['POST'])
def re_ai_job(job_id):
    """Re-process a job with AI (priority queue)."""
    job_store = get_job_store()
    ai_processor = get_ai_processor()
    
    data = request.json or {}
    custom_prompt = data.get('custom_prompt', '')
    
    # Update job with custom prompt and reset to queued
    updates = {
        'status': JobStatus.QUEUED_FOR_AI,
        'custom_prompt': custom_prompt,
        'priority': 1
    }
    
    success = job_store.update_job(job_id, updates)
    
    if success:
        # Add to priority queue
        ai_processor.add_priority_job(job_id)
        return jsonify({'success': True, 'message': 'Job added to priority queue'})
    else:
        return jsonify({'error': 'Job not found'}), 404


@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a job."""
    job_store = get_job_store()
    success = job_store.delete_job(job_id)
    
    if success:
        return jsonify({'success': True, 'message': 'Job deleted'})
    else:
        return jsonify({'error': 'Job not found'}), 404


@app.route('/api/config', methods=['GET'])
def get_config_api():
    """Get current configuration."""
    config = get_config()
    config_data = config.get_all()
    
    # Don't send API keys to frontend
    return jsonify(config_data)


@app.route('/api/config', methods=['POST'])
def update_config_api():
    """Update configuration."""
    config = get_config()
    data = request.json
    
    # Update configuration
    config.update(data)
    
    return jsonify({'success': True, 'message': 'Configuration updated'})


@app.route('/api/models', methods=['GET'])
def get_models():
    """Get available models for current AI provider."""
    ai_processor = get_ai_processor()
    
    try:
        models = ai_processor.get_available_models()
        return jsonify({'models': models})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get statistics about jobs."""
    job_store = get_job_store()
    
    queued = len(job_store.get_jobs_by_status(JobStatus.QUEUED_FOR_AI))
    processing = len(job_store.get_jobs_by_status(JobStatus.PROCESSING_AI))
    pending = len(job_store.get_jobs_by_status(JobStatus.PENDING_COMPLETION))
    completed = len(job_store.get_jobs_by_status(JobStatus.COMPLETED))
    failed = len(job_store.get_jobs_by_status(JobStatus.FAILED))
    
    return jsonify({
        'queued': queued,
        'processing': processing,
        'pending': pending,
        'completed': completed,
        'failed': failed,
        'total': queued + processing + pending + completed + failed
    })


def create_app():
    """Create and configure the Flask application."""
    return app


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7000, debug=True)
