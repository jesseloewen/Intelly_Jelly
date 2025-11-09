// Intelly Jelly - Main JavaScript

let autoRefreshInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadJobs();
    loadStats();
    setupAutoRefresh();
});

// Auto-refresh functionality
function setupAutoRefresh() {
    const checkbox = document.getElementById('auto-refresh');
    
    if (checkbox.checked) {
        startAutoRefresh();
    }
    
    checkbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });
}

function startAutoRefresh() {
    stopAutoRefresh(); // Clear any existing interval
    autoRefreshInterval = setInterval(() => {
        loadJobs();
        loadStats();
    }, 3000);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// Load statistics
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        
        document.getElementById('stat-queued').textContent = stats.queued;
        document.getElementById('stat-processing').textContent = stats.processing;
        document.getElementById('stat-pending').textContent = stats.pending;
        document.getElementById('stat-completed').textContent = stats.completed;
        document.getElementById('stat-failed').textContent = stats.failed;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load jobs
async function loadJobs() {
    const container = document.getElementById('jobs-container');
    const statusFilter = document.getElementById('status-filter').value;
    
    try {
        let url = '/api/jobs';
        if (statusFilter) {
            url += `?status=${statusFilter}`;
        }
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.jobs.length === 0) {
            container.innerHTML = '<p class="loading">No jobs found</p>';
            return;
        }
        
        container.innerHTML = data.jobs.map(job => createJobCard(job)).join('');
    } catch (error) {
        container.innerHTML = '<p class="error-message">Error loading jobs: ' + error.message + '</p>';
    }
}

// Create job card HTML
function createJobCard(job) {
    const statusClass = `status-${job.status}`;
    const statusText = job.status.replace(/_/g, ' ');
    
    let detailsHTML = '';
    
    if (job.new_name) {
        detailsHTML += `
            <div class="job-detail-row">
                <span class="job-detail-label">New Name:</span>
                <span class="job-new-name">${escapeHtml(job.new_name)}</span>
            </div>
        `;
    }
    
    if (job.subfolder) {
        detailsHTML += `
            <div class="job-detail-row">
                <span class="job-detail-label">Subfolder:</span>
                ${escapeHtml(job.subfolder)}
            </div>
        `;
    }
    
    if (job.error_message) {
        detailsHTML += `
            <div class="job-detail-row">
                <span class="error-message">Error: ${escapeHtml(job.error_message)}</span>
            </div>
        `;
    }
    
    // Action buttons based on status
    let actionsHTML = '';
    
    if (job.status !== 'completed') {
        actionsHTML += `
            <button class="btn btn-primary" onclick="openEditModal('${job.job_id}')">
                ✏️ Edit
            </button>
        `;
    }
    
    if (job.status !== 'processing_ai' && job.status !== 'completed') {
        actionsHTML += `
            <button class="btn" onclick="openReAIModal('${job.job_id}')">
                🤖 Re-AI
            </button>
        `;
    }
    
    actionsHTML += `
        <button class="btn btn-danger" onclick="deleteJob('${job.job_id}')">
            🗑️ Delete
        </button>
    `;
    
    return `
        <div class="job-card">
            <div class="job-header">
                <div class="job-filename">${escapeHtml(job.original_filename)}</div>
                <div class="job-status ${statusClass}">${statusText}</div>
            </div>
            <div class="job-details">
                ${detailsHTML}
            </div>
            <div class="job-actions">
                ${actionsHTML}
            </div>
        </div>
    `;
}

// Edit job modal
function openEditModal(jobId) {
    fetch(`/api/jobs/${jobId}`)
        .then(response => response.json())
        .then(job => {
            document.getElementById('edit-job-id').value = job.job_id;
            document.getElementById('edit-original').value = job.original_filename;
            document.getElementById('edit-new-name').value = job.new_name || '';
            document.getElementById('edit-subfolder').value = job.subfolder || '';
            
            document.getElementById('edit-modal').style.display = 'block';
        })
        .catch(error => {
            alert('Error loading job: ' + error.message);
        });
}

function closeEditModal() {
    document.getElementById('edit-modal').style.display = 'none';
}

async function saveJobEdit(event) {
    event.preventDefault();
    
    const jobId = document.getElementById('edit-job-id').value;
    const newName = document.getElementById('edit-new-name').value;
    const subfolder = document.getElementById('edit-subfolder').value;
    
    try {
        const response = await fetch(`/api/jobs/${jobId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                new_name: newName,
                subfolder: subfolder
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            closeEditModal();
            loadJobs();
            loadStats();
        } else {
            alert('Error updating job: ' + (result.error || 'Unknown error'));
        }
    } catch (error) {
        alert('Error updating job: ' + error.message);
    }
}

// Re-AI modal
function openReAIModal(jobId) {
    fetch(`/api/jobs/${jobId}`)
        .then(response => response.json())
        .then(job => {
            document.getElementById('reai-job-id').value = job.job_id;
            document.getElementById('reai-original').value = job.original_filename;
            document.getElementById('reai-prompt').value = job.custom_prompt || '';
            document.getElementById('reai-use-default').checked = true;
            
            document.getElementById('reai-modal').style.display = 'block';
        })
        .catch(error => {
            alert('Error loading job: ' + error.message);
        });
}

function closeReAIModal() {
    document.getElementById('reai-modal').style.display = 'none';
}

async function submitReAI(event) {
    event.preventDefault();
    
    const jobId = document.getElementById('reai-job-id').value;
    const customPrompt = document.getElementById('reai-prompt').value;
    const useDefault = document.getElementById('reai-use-default').checked;
    
    try {
        const response = await fetch(`/api/jobs/${jobId}/re-ai`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                custom_prompt: customPrompt,
                use_default_instructions: useDefault
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            closeReAIModal();
            loadJobs();
            loadStats();
            alert('Job added to priority queue for re-processing');
        } else {
            alert('Error re-processing job: ' + (result.error || 'Unknown error'));
        }
    } catch (error) {
        alert('Error re-processing job: ' + error.message);
    }
}

// Delete job
async function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this job?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/jobs/${jobId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            loadJobs();
            loadStats();
        } else {
            alert('Error deleting job: ' + (result.error || 'Unknown error'));
        }
    } catch (error) {
        alert('Error deleting job: ' + error.message);
    }
}

// Utility function to escape HTML
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// Close modals when clicking outside
window.onclick = function(event) {
    const editModal = document.getElementById('edit-modal');
    const reaiModal = document.getElementById('reai-modal');
    
    if (event.target === editModal) {
        closeEditModal();
    }
    if (event.target === reaiModal) {
        closeReAIModal();
    }
}
