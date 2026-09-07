document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('download-form');
    const urlInput = document.getElementById('url-input');
    const modeRadios = document.querySelectorAll('input[name="download-mode"]');
    const channelOptions = document.getElementById('channel-options');
    const dateFromInput = document.getElementById('date-from');
    const dateToInput = document.getElementById('date-to');
    const mediaAll = document.getElementById('media-all');
    const mediaVideos = document.getElementById('media-videos');
    const mediaShorts = document.getElementById('media-shorts');
    const mediaStreams = document.getElementById('media-streams');
    const formMessage = document.getElementById('form-message');
    const submitBtn = document.getElementById('submit-btn');

    // Get current active mode
    function getActiveMode() {
        const checked = document.querySelector('input[name="download-mode"]:checked');
        return checked ? checked.value : 'single';
    }

    // Set active mode and update UI visibility
    function setActiveMode(mode) {
        const targetRadio = document.querySelector(`input[name="download-mode"][value="${mode}"]`);
        if (targetRadio) {
            targetRadio.checked = true;
            handleModeChange(mode);
        }
    }

    function handleModeChange(mode) {
        if (mode === 'channel') {
            channelOptions.classList.remove('hidden');
        } else {
            channelOptions.classList.add('hidden');
        }
    }

    modeRadios.forEach(radio => {
        radio.addEventListener('change', () => {
            handleModeChange(radio.value);
        });
    });

    // Auto-detect playlist and channel URLs
    const isPlaylistUrl = (url) => /[?&]list=|\/playlist/.test(url || '');
    const isChannelUrl = (url) => /\/(@|channel\/|c\/|user\/)/.test(url || '');

    function autoDetectMode(value) {
        if (isChannelUrl(value)) {
            setActiveMode('channel');
        } else if (isPlaylistUrl(value)) {
            setActiveMode('playlist');
        }
    }

    urlInput.addEventListener('input', (e) => {
        autoDetectMode(e.target.value);
    });

    urlInput.addEventListener('paste', (e) => {
        const pastedText = (e.clipboardData || window.clipboardData)?.getData('text');
        if (pastedText) {
            autoDetectMode(pastedText);
        } else if (urlInput.value) {
            autoDetectMode(urlInput.value);
        }
        setTimeout(() => autoDetectMode(urlInput.value), 0);
    });

    // Handle Media Filter Checkboxes
    function updateMediaCheckboxes() {
        const isAll = mediaAll.checked;
        const subCheckboxes = [mediaVideos, mediaShorts, mediaStreams];
        subCheckboxes.forEach(cb => {
            cb.disabled = isAll;
            const label = cb.closest('.media-checkbox-label');
            if (label) {
                label.classList.toggle('disabled', isAll);
            }
        });
        if (!isAll) {
            const anyChecked = subCheckboxes.some(cb => cb.checked);
            if (!anyChecked) {
                mediaVideos.checked = true;
            }
        }
    }

    if (mediaAll) {
        mediaAll.addEventListener('change', updateMediaCheckboxes);
        updateMediaCheckboxes();
    }

    [mediaVideos, mediaShorts, mediaStreams].forEach(cb => {
        if (cb) {
            cb.addEventListener('change', () => {
                const subCheckboxes = [mediaVideos, mediaShorts, mediaStreams];
                const anyChecked = subCheckboxes.some(c => c.checked);
                if (!anyChecked && mediaAll) {
                    mediaAll.checked = true;
                    updateMediaCheckboxes();
                }
            });
        }
    });

    // State for polling
    let pollTimer = null;
    let isPolling = false;
    let basePollInterval = 1500;
    let maxPollInterval = 10000;
    let currentPollInterval = basePollInterval;

    // Initial fetch
    scheduleNextPoll(0);

    const modal = document.getElementById('confirmation-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalText = document.getElementById('modal-text');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');

    let pendingPlaylistUrl = null;
    let pendingChannelItems = null;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = urlInput.value.trim();
        const mode = getActiveMode();
        if (!url) return;

        submitBtn.disabled = true;

        if (mode === 'channel') {
            const dateFrom = dateFromInput.value;
            const dateTo = dateToInput.value;

            if (!dateFrom || !dateTo) {
                showMessage('Please select both From Date and To Date.', 'msg-error');
                submitBtn.disabled = false;
                return;
            }

            if (dateFrom > dateTo) {
                showMessage('From Date must be earlier than or equal to To Date.', 'msg-error');
                submitBtn.disabled = false;
                return;
            }

            let mediaTypes = [];
            if (mediaAll && mediaAll.checked) {
                mediaTypes = ['all'];
            } else {
                if (mediaVideos && mediaVideos.checked) mediaTypes.push('videos');
                if (mediaShorts && mediaShorts.checked) mediaTypes.push('shorts');
                if (mediaStreams && mediaStreams.checked) mediaTypes.push('streams');
                if (mediaTypes.length === 0) mediaTypes = ['all'];
            }

            showMessage('Scanning channel date range with PID logarithmic search...', 'msg-info');

            try {
                const response = await fetch('/api/channel-scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: url,
                        date_from: dateFrom,
                        date_to: dateTo,
                        media_types: mediaTypes
                    })
                });

                const data = await response.json().catch(() => ({}));

                if (response.ok) {
                    if (!data.count || data.count === 0) {
                        showMessage(`No videos found between ${data.date_from} and ${data.date_to}.`, 'msg-info');
                        submitBtn.disabled = false;
                    } else {
                        modalTitle.textContent = data.channel_title ? `${data.channel_title} - Date Scan` : 'Channel Scan Results';
                        modalText.textContent = `Found ${data.count} video${data.count !== 1 ? 's' : ''} between ${data.date_from} and ${data.date_to}. Queue all?`;
                        pendingChannelItems = data.items;
                        pendingPlaylistUrl = null;
                        modal.classList.remove('hidden');
                        showMessage('', '');
                    }
                } else {
                    showMessage(data.detail || 'Failed to scan channel', 'msg-error');
                    submitBtn.disabled = false;
                }
            } catch (err) {
                showMessage('Network error while scanning channel', 'msg-error');
                submitBtn.disabled = false;
            }
        } else if (mode === 'playlist') {
            showMessage('Fetching playlist info...', 'msg-info');
            try {
                const infoRes = await fetch(`/api/playlist-info?url=${encodeURIComponent(url)}`);
                const infoData = await infoRes.json().catch(() => ({}));
                
                if (infoRes.ok) {
                    modalTitle.textContent = infoData.title || 'Playlist Details';
                    const count = infoData.count;
                    modalText.textContent = `This playlist contains ${count} video${count !== 1 ? 's' : ''}. Queue all?`;
                    
                    pendingPlaylistUrl = url;
                    pendingChannelItems = null;
                    modal.classList.remove('hidden');
                    showMessage('', '');
                } else {
                    showMessage(infoData.detail || 'Failed to fetch playlist info', 'msg-error');
                    submitBtn.disabled = false;
                }
            } catch (err) {
                showMessage('Network error while fetching playlist info', 'msg-error');
                submitBtn.disabled = false;
            }
        } else {
            await queueUrl(url, false);
            submitBtn.disabled = false;
        }
    });

    modalCancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
        pendingPlaylistUrl = null;
        pendingChannelItems = null;
        submitBtn.disabled = false;
    });

    modalConfirmBtn.addEventListener('click', async () => {
        if (pendingChannelItems) {
            modalConfirmBtn.disabled = true;
            modalConfirmBtn.textContent = 'Queueing...';

            try {
                const response = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: pendingChannelItems })
                });

                const data = await response.json().catch(() => ({}));

                if (response.ok) {
                    const count = pendingChannelItems.length;
                    showMessage(`Successfully queued ${count} video${count !== 1 ? 's' : ''}!`, 'msg-success');
                    urlInput.value = '';
                    setActiveMode('single');
                    scheduleNextPoll(0);
                } else {
                    showMessage(data.detail || 'Failed to queue channel videos', 'msg-error');
                }
            } catch (err) {
                showMessage('Network error while queuing channel videos', 'msg-error');
            } finally {
                modal.classList.add('hidden');
                modalConfirmBtn.disabled = false;
                modalConfirmBtn.textContent = 'Queue All';
                pendingChannelItems = null;
                submitBtn.disabled = false;
            }
        } else if (pendingPlaylistUrl) {
            modalConfirmBtn.disabled = true;
            modalConfirmBtn.textContent = 'Queueing...';
            
            await queueUrl(pendingPlaylistUrl, true);
            
            modal.classList.add('hidden');
            modalConfirmBtn.disabled = false;
            modalConfirmBtn.textContent = 'Queue All';
            pendingPlaylistUrl = null;
            submitBtn.disabled = false;
        }
    });

    async function queueUrl(url, isPlaylist) {
        showMessage(isPlaylist ? 'Adding playlist to queue...' : 'Adding to queue...', 'msg-info');

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
                setActiveMode('single');
                scheduleNextPoll(0);
            } else {
                showMessage(data.detail || 'Failed to add to queue', 'msg-error');
            }
        } catch (err) {
            showMessage('Network error occurred while adding to queue', 'msg-error');
        }
    }

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
