document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('download-form');
    const urlInput = document.getElementById('url-input');
    const formMessage = document.getElementById('form-message');
    const submitBtn = document.getElementById('submit-btn');

    // State for polling
    let pollTimer = null;
    let isPolling = false;
    let basePollInterval = 1500;
    let maxPollInterval = 10000;
    let currentPollInterval = basePollInterval;

    // Initial fetch
    scheduleNextPoll(0);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = urlInput.value.trim();
        const isPlaylist = document.getElementById('playlist-toggle').checked;
        if (!url) return;

        submitBtn.disabled = true;
        showMessage(isPlaylist ? 'Parsing playlist...' : 'Adding to queue...', 'msg-info');

        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, is_playlist: isPlaylist })
            });

            const data = await response.json().catch(() => ({}));

            if (response.ok) {
                showMessage(isPlaylist ? 'Playlist parsing started! Videos will appear in queue shortly.' : 'Successfully added to queue!', 'msg-success');
                urlInput.value = '';
                // Force an immediate update
                scheduleNextPoll(0);
            } else {
                showMessage(data.detail || 'Failed to add to queue', 'msg-error');
            }
        } catch (err) {
            showMessage('Network error occurred while adding to queue', 'msg-error');
        } finally {
            submitBtn.disabled = false;
        }
    });

    // Event delegation for cancel buttons
    document.body.addEventListener('click', async (e) => {
        if (e.target.classList.contains('btn-cancel')) {
            const taskId = e.target.dataset.taskId;
            if (!taskId) return;
            
            const btn = e.target;
            const originalText = btn.textContent;
            btn.textContent = 'Canceling...';
            btn.disabled = true;

            try {
                const response = await fetch(`/api/cancel/${taskId}`, { method: 'DELETE' });
                if (response.ok) {
                    scheduleNextPoll(0);
                } else {
                    console.error("Failed to cancel task");
                    btn.textContent = 'Failed';
                    setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
                }
            } catch (err) {
                console.error("Error cancelling task", err);
                btn.textContent = 'Error';
                setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
            }
        }
    });

    function showMessage(text, className) {
        formMessage.textContent = text;
        formMessage.className = className;
        
        if (className === 'msg-success' || className === 'msg-info') {
            setTimeout(() => {
                if (formMessage.textContent === text) {
                    formMessage.textContent = '';
                    formMessage.className = '';
                }
            }, 4000);
        }
    }

    async function updateStatus() {
        if (isPolling) return;
        isPolling = true;

        try {
            const response = await fetch('/api/status');
            if (!response.ok) throw new Error('Network response was not ok');
            
            const data = await response.json();
            
            renderCurrent(data.current);
            renderQueued(data.queued);
            renderHistory(data.history);

            // Determine if there are active or queued tasks
            const activeTasksExist = !!data.current || (data.queued && data.queued.length > 0);
            
            // Adjust polling interval based on activity
            if (activeTasksExist) {
                currentPollInterval = basePollInterval;
            } else {
                currentPollInterval = Math.min(currentPollInterval * 1.5, maxPollInterval);
            }

        } catch (err) {
            console.error('Failed to fetch status', err);
            // On error, exponential backoff
            currentPollInterval = Math.min(currentPollInterval * 2, maxPollInterval);
        } finally {
            isPolling = false;
            scheduleNextPoll(currentPollInterval);
        }
    }

    function scheduleNextPoll(delay) {
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = setTimeout(updateStatus, delay);
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
            const progress = task.progress || 0;
            progressHtml = `
                <div class="progress-container">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${escapeHtml(progress)}%"></div>
                    </div>
                </div>
                <div class="task-stats">
                    <span>${escapeHtml(progress)}%</span>
                    <span>ETA: ${escapeHtml(task.eta) || 'Calculating...'}</span>
                </div>
            `;
        }

        div.innerHTML = `
            <div class="task-header">
                <div style="flex: 1; overflow: hidden; padding-right: 1rem;">
                    <div class="task-title">${escapeHtml(task.title || 'Unknown Title')}</div>
                    <div class="task-url">${escapeHtml(task.url)}</div>
                </div>
                ${isPending ? `<button class="btn-cancel" data-task-id="${escapeHtml(task.id)}">Cancel</button>` : ''}
            </div>
            
            ${progressHtml}
            
            <div class="task-meta">
                <span class="status-indicator">
                    <div class="dot ${escapeHtml(task.status)}"></div>
                    ${escapeHtml(task.status).charAt(0).toUpperCase() + escapeHtml(task.status).slice(1)}
                </span>
                <span>Size: ${escapeHtml(task.size) || 'Unknown'} | Added: ${addedAt}</span>
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
        count.textContent = queued ? queued.length : 0;
        
        if (queued && queued.length > 0) {
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
        
        if (history && history.length > 0) {
            history.forEach(task => {
                container.appendChild(createTaskElement(task));
            });
        } else {
            container.innerHTML = '<p class="empty-state">No history</p>';
        }
    }

    function escapeHtml(unsafe) {
        if (unsafe == null) return '';
        return String(unsafe)
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }
});
