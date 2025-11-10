from flask import Flask, render_template, request, jsonify
import threading
import os
import logging

from backend.config_manager import ConfigManager
from backend.job_store import JobStore, JobStatus
from backend.backend_orchestrator import BackendOrchestrator
from backend.ai_processor import AIProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('intelly_jelly.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

config_manager = ConfigManager()
job_store = JobStore()
orchestrator = BackendOrchestrator(config_manager, job_store)
ai_processor = AIProcessor(config_manager)

backend_thread = None


def start_backend():
    orchestrator.start()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/settings')
def settings():
    return render_template('settings.html')


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
        enable_web_search = data.get('enable_web_search', False)
        logger.debug(f"Re-AI job data: custom_prompt={bool(custom_prompt)}, include_instructions={include_instructions}, include_filename={include_filename}, enable_web_search={enable_web_search}")
        
        success = orchestrator.re_ai_job(job_id, custom_prompt, include_instructions, include_filename, enable_web_search)
        
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
def update_config():
    data = request.json
    
    allowed_fields = [
        'DOWNLOADING_PATH',
        'COMPLETED_PATH',
        'LIBRARY_PATH',
        'INSTRUCTIONS_FILE_PATH',
        'AI_PROVIDER',
        'AI_MODEL',
        'DRY_RUN_MODE',
        'ENABLE_WEB_SEARCH'
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


if __name__ == '__main__':
    os.makedirs('./test_folders/downloading', exist_ok=True)
    os.makedirs('./test_folders/completed', exist_ok=True)
    os.makedirs('./test_folders/library', exist_ok=True)
    
    backend_thread = threading.Thread(target=start_backend, daemon=True)
    backend_thread.start()
    
    print("Starting Flask server on http://localhost:7000")
    app.run(host='0.0.0.0', port=7000, debug=False, threaded=True)
