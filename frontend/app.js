document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('download-form');
    const urlInput = document.getElementById('url-input');
    const formMessage = document.getElementById('form-message');
    const submitBtn = document.getElementById('submit-btn');

    // Fetch and update status every 1.5 seconds
    setInterval(updateStatus, 1500);
    updateStatus();

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = urlInput.value.trim();
        const isPlaylist = document.getElementById('playlist-toggle').checked;
        if (!url) return;

        submitBtn.disabled = true;
        formMessage.textContent = isPlaylist ? 'Parsing playlist...' : 'Adding to queue...';
        formMessage.className = '';

        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ url, is_playlist: isPlaylist })
            });

            const data = await response.json();

            if (response.ok) {
                formMessage.textContent = isPlaylist ? 'Playlist parsing started! Videos will appear in queue shortly.' : 'Successfully added to queue!';
                formMessage.className = 'msg-success';
                urlInput.value = '';
                updateStatus();
            } else {
                formMessage.textContent = data.detail || 'Failed to add to queue';
                formMessage.className = 'msg-error';
            }
        } catch (err) {
            formMessage.textContent = 'Network error occurred';
            formMessage.className = 'msg-error';
        } finally {
            submitBtn.disabled = false;
            setTimeout(() => {
                if (formMessage.className === 'msg-success') {
                    formMessage.textContent = '';
                }
            }, 3000);
        }
    });
});

window.cancelTask = async function(taskId) {
    try {
        const response = await fetch(`/api/cancel/${taskId}`, { method: 'DELETE' });
        if (response.ok) {
            updateStatus();
        } else {
            console.error("Failed to cancel task");
        }
    } catch (e) {
        console.error("Error cancelling task", e);
    }
};

async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) return;
        
        const data = await response.json();
        renderCurrent(data.current);
        renderQueued(data.queued);
        renderHistory(data.history);
    } catch (err) {
        console.error('Failed to fetch status', err);
    }
}

function createTaskElement(task) {
    const div = document.createElement('div');
    div.className = 'task-item';
    
    const addedAt = new Date(task.added_at).toLocaleTimeString();
    
    let errorHtml = '';
    if (task.error) {
        errorHtml = `<div class="task-error">${escapeHtml(task.error)}</div>`;
    }

    const isPending = task.status === 'queued' || task.status === 'downloading';
    
    let progressHtml = '';
    if (task.status === 'downloading') {
        progressHtml = `
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${task.progress || 0}%"></div>
                </div>
            </div>
            <div class="task-stats">
                <span>${task.progress || 0}%</span>
                <span>ETA: ${task.eta || 'Calculating...'}</span>
            </div>
        `;
    }

    div.innerHTML = `
        <div class="task-header">
            <div style="flex: 1; overflow: hidden; padding-right: 1rem;">
                <div class="task-title">${escapeHtml(task.title || 'Unknown Title')}</div>
                <div class="task-url">${escapeHtml(task.url)}</div>
            </div>
            ${isPending ? `<button class="btn-cancel" onclick="cancelTask('${task.id}')">Cancel</button>` : ''}
        </div>
        
        ${progressHtml}
        
        <div class="task-meta">
            <span class="status-indicator">
                <div class="dot ${task.status}"></div>
                ${task.status.charAt(0).toUpperCase() + task.status.slice(1)}
            </span>
            <span>Size: ${task.size || 'Unknown'} | Added: ${addedAt}</span>
        </div>
        ${errorHtml}
    `;
    return div;
}

function renderCurrent(current) {
    const container = document.getElementById('current-task');
    container.innerHTML = '';
    if (current) {
        container.appendChild(createTaskElement(current));
    } else {
        container.innerHTML = '<p class="empty-state">No active downloads</p>';
    }
}

function renderQueued(queued) {
    const container = document.getElementById('queued-tasks');
    const count = document.getElementById('queue-count');
    
    container.innerHTML = '';
    count.textContent = queued.length;
    
    if (queued.length > 0) {
        queued.forEach(task => {
            container.appendChild(createTaskElement(task));
        });
    } else {
        container.innerHTML = '<p class="empty-state">Queue is empty</p>';
    }
}

function renderHistory(history) {
    const container = document.getElementById('history-tasks');
    container.innerHTML = '';
    
    if (history.length > 0) {
        history.forEach(task => {
            container.appendChild(createTaskElement(task));
        });
    } else {
        container.innerHTML = '<p class="empty-state">No history</p>';
    }
}

function escapeHtml(unsafe) {
    return (unsafe || '').replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}
