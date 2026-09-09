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

    // Auth & Account Elements
    const accountBadgeBtn = document.getElementById('account-badge-btn');
    const accountUsername = document.getElementById('account-username');
    const loginModal = document.getElementById('login-modal');
    const loginModalTitle = document.getElementById('login-modal-title');
    const loginModalSubtitle = document.getElementById('login-modal-subtitle');
    const loginForm = document.getElementById('login-form');
    const loginUsernameInput = document.getElementById('login-username');
    const loginPasswordInput = document.getElementById('login-password');
    const loginSubmitBtn = document.getElementById('login-submit-btn');
    const loginErrorMsg = document.getElementById('login-error-msg');

    const accountModal = document.getElementById('account-modal');
    const accountModalCloseBtn = document.getElementById('account-modal-close-btn');
    const changePasswordForm = document.getElementById('change-password-form');
    const currentPasswordInput = document.getElementById('current-password');
    const newPasswordInput = document.getElementById('new-password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    const changePassSubmitBtn = document.getElementById('change-pass-submit-btn');
    const changePassMsg = document.getElementById('change-pass-msg');
    const logoutBtn = document.getElementById('logout-btn');

    let isSetupMode = false;
    let currentUser = null;

    // Theme Management (Light/Dark mode)
    const themeToggleBtn = document.getElementById('theme-toggle-btn');

    function getPreferredTheme() {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light' || savedTheme === 'dark') {
            return savedTheme;
        }
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            return 'light';
        }
        return 'dark';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        if (themeToggleBtn) {
            const isDark = theme === 'dark';
            themeToggleBtn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
            themeToggleBtn.setAttribute('title', isDark ? 'Switch to light mode' : 'Switch to dark mode');
        }
    }

    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', newTheme);
        applyTheme(newTheme);
    }

    // Initialize Theme
    applyTheme(getPreferredTheme());

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', toggleTheme);
    }

    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
            if (!localStorage.getItem('theme')) {
                applyTheme(e.matches ? 'light' : 'dark');
            }
        });
    }

    // Get current active mode
    function getActiveMode() {
        const checked = document.querySelector('input[name="download-mode"]:checked');
        return checked ? checked.value : 'single';
    }

    // Set active mode and update UI visibility immediately
    function setActiveMode(mode) {
        const targetRadio = document.querySelector(`input[name="download-mode"][value="${mode}"]`);
        if (targetRadio) {
            targetRadio.checked = true;
        }
        handleModeChange(mode);
    }

    function handleModeChange(mode) {
        if (!channelOptions) return;
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
        radio.addEventListener('input', () => {
            handleModeChange(radio.value);
        });
    });

    document.querySelectorAll('.segment-label').forEach(label => {
        label.addEventListener('click', () => {
            const forId = label.getAttribute('for');
            const radio = document.getElementById(forId);
            if (radio) {
                radio.checked = true;
                handleModeChange(radio.value);
            }
        });
    });

    // Ensure initial mode is cleanly synced
    handleModeChange(getActiveMode());

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

    // Initial auth check and status load
    checkAuthStatus();

    const modal = document.getElementById('confirmation-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalText = document.getElementById('modal-text');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');

    let pendingPlaylistUrl = null;
    let pendingChannelItems = null;

    const searchResultsContainer = document.getElementById('search-results-container');
    const searchResultsList = document.getElementById('search-results-list');
    const closeSearchBtn = document.getElementById('close-search-btn');

    if (closeSearchBtn) {
        closeSearchBtn.addEventListener('click', () => {
            searchResultsContainer.classList.add('hidden');
        });
    }

    async function performSearch(query) {
        searchResultsContainer.classList.remove('hidden');
        searchResultsList.innerHTML = `
            <div class="search-spinner">
                <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="12" y1="2" x2="12" y2="6"></line>
                    <line x1="12" y1="18" x2="12" y2="22"></line>
                    <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
                    <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
                    <line x1="2" y1="12" x2="6" y2="12"></line>
                    <line x1="18" y1="12" x2="22" y2="12"></line>
                    <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
                    <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
                </svg>
            </div>
        `;

        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            if (!response.ok) throw new Error('Search failed');
            const data = await response.json();
            
            searchResultsList.innerHTML = '';
            if (!data.results || data.results.length === 0) {
                searchResultsList.innerHTML = '<div style="padding: 1rem; color: var(--text-secondary); text-align: center;">No results found</div>';
                return;
            }

            data.results.forEach(item => {
                const isChannel = item.type === 'channel';
                const el = document.createElement('div');
                el.className = 'search-result-item';
                el.innerHTML = `
                    <img src="${item.thumbnail}" alt="" class="search-result-thumbnail ${isChannel ? 'channel-thumb' : ''}">
                    <div class="search-result-info">
                        <div class="search-result-title">${item.title}</div>
                        <div class="search-result-meta">
                            ${isChannel ? '<span class="search-result-badge">Channel</span>' : ''}
                            ${!isChannel && item.duration ? `<span class="search-result-badge">${item.duration}</span>` : ''}
                            <span>${isChannel ? item.handle : item.channel}</span>
                        </div>
                    </div>
                `;
                el.addEventListener('click', () => {
                    urlInput.value = item.url;
                    searchResultsContainer.classList.add('hidden');
                    
                    // Auto-switch mode based on selection
                    if (isChannel && document.getElementById('mode-channel')) {
                        document.getElementById('mode-channel').checked = true;
                        handleModeChange('channel');
                    } else if (!isChannel && document.getElementById('mode-single')) {
                        document.getElementById('mode-single').checked = true;
                        handleModeChange('single');
                    }
                    
                    // Trigger download immediately
                    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                });
                searchResultsList.appendChild(el);
            });
        } catch (error) {
            searchResultsList.innerHTML = '<div style="padding: 1rem; color: var(--color-error); text-align: center;">Error performing search</div>';
        }
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = urlInput.value.trim();
        const mode = getActiveMode();
        if (!url) return;

        // If not a URL, perform a search instead
        if (!/^https?:\/\//i.test(url)) {
            performSearch(url);
            return;
        }

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
            if (response.status === 401) {
                enableLoginMode();
                return;
            }
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

    // -----------------------------------------------------------------------
    // Authentication & Session Management
    // -----------------------------------------------------------------------

    async function checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/status');
            const data = await response.json().catch(() => ({}));

            if (data.setup_required) {
                enableSetupMode();
                return false;
            } else if (!data.authenticated) {
                enableLoginMode();
                return false;
            } else {
                setAuthenticatedState(data.username);
                scheduleNextPoll(0);
                return true;
            }
        } catch (err) {
            enableLoginMode();
            return false;
        }
    }

    function enableSetupMode() {
        isSetupMode = true;
        stopPolling();
        if (accountBadgeBtn) accountBadgeBtn.classList.add('hidden');
        if (loginModalTitle) loginModalTitle.textContent = 'Welcome - Initial Setup';
        if (loginModalSubtitle) loginModalSubtitle.textContent = 'Create an administrator username and password to secure your instance.';
        if (loginSubmitBtn) loginSubmitBtn.textContent = 'Create Account & Sign In';
        if (loginPasswordInput) loginPasswordInput.setAttribute('autocomplete', 'new-password');
        showAuthError(loginErrorMsg, '');
        if (loginModal) loginModal.classList.remove('hidden');
        if (loginUsernameInput) loginUsernameInput.focus();
    }

    function enableLoginMode() {
        isSetupMode = false;
        stopPolling();
        if (accountBadgeBtn) accountBadgeBtn.classList.add('hidden');
        if (loginModalTitle) loginModalTitle.textContent = 'Authentication Required';
        if (loginModalSubtitle) loginModalSubtitle.textContent = 'Enter your credentials to manage downloads and playlists.';
        if (loginSubmitBtn) loginSubmitBtn.textContent = 'Log In';
        if (loginPasswordInput) loginPasswordInput.setAttribute('autocomplete', 'current-password');
        showAuthError(loginErrorMsg, '');
        if (loginModal) loginModal.classList.remove('hidden');
        if (loginUsernameInput) loginUsernameInput.focus();
    }

    function setAuthenticatedState(username) {
        currentUser = username || 'admin';
        if (accountUsername) accountUsername.textContent = currentUser;
        if (accountBadgeBtn) accountBadgeBtn.classList.remove('hidden');
        if (loginModal) loginModal.classList.add('hidden');
        if (loginPasswordInput) loginPasswordInput.value = '';
        showAuthError(loginErrorMsg, '');
    }

    function stopPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
        isPolling = false;
    }

    function showAuthError(element, text) {
        if (!element) return;
        if (!text) {
            element.textContent = '';
            element.classList.add('hidden');
        } else {
            element.textContent = text;
            element.classList.remove('hidden');
        }
    }

    function showAuthMessage(element, text, typeClass) {
        if (!element) return;
        if (!text) {
            element.textContent = '';
            element.className = 'auth-message hidden';
        } else {
            element.textContent = text;
            element.className = `auth-message ${typeClass}`;
        }
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = loginUsernameInput ? loginUsernameInput.value.trim() : '';
            const password = loginPasswordInput ? loginPasswordInput.value : '';

            if (!username || !password) {
                showAuthError(loginErrorMsg, 'Username and password are required.');
                return;
            }

            if (loginSubmitBtn) {
                loginSubmitBtn.disabled = true;
                loginSubmitBtn.textContent = isSetupMode ? 'Creating Account...' : 'Signing In...';
            }
            showAuthError(loginErrorMsg, '');

            const endpoint = isSetupMode ? '/api/auth/setup' : '/api/auth/login';

            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json().catch(() => ({}));

                if (response.ok && data.success) {
                    setAuthenticatedState(data.username || username);
                    currentPollInterval = basePollInterval;
                    scheduleNextPoll(0);
                } else {
                    showAuthError(loginErrorMsg, data.detail || 'Authentication failed. Please verify your credentials.');
                }
            } catch (err) {
                showAuthError(loginErrorMsg, 'Network error during authentication. Please try again.');
            } finally {
                if (loginSubmitBtn) {
                    loginSubmitBtn.disabled = false;
                    loginSubmitBtn.textContent = isSetupMode ? 'Create Account & Sign In' : 'Log In';
                }
            }
        });
    }

    if (accountBadgeBtn) {
        accountBadgeBtn.addEventListener('click', () => {
            if (changePasswordForm) changePasswordForm.reset();
            showAuthMessage(changePassMsg, '', '');
            if (accountModal) accountModal.classList.remove('hidden');
            if (currentPasswordInput) currentPasswordInput.focus();
        });
    }

    if (accountModalCloseBtn) {
        accountModalCloseBtn.addEventListener('click', () => {
            if (accountModal) accountModal.classList.add('hidden');
            if (changePasswordForm) changePasswordForm.reset();
            showAuthMessage(changePassMsg, '', '');
        });
    }

    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const currentPassword = currentPasswordInput ? currentPasswordInput.value : '';
            const newPassword = newPasswordInput ? newPasswordInput.value : '';
            const confirmPassword = confirmPasswordInput ? confirmPasswordInput.value : '';

            if (newPassword !== confirmPassword) {
                showAuthMessage(changePassMsg, 'New passwords do not match.', 'auth-error');
                return;
            }

            if (newPassword.length < 4) {
                showAuthMessage(changePassMsg, 'New password must be at least 4 characters long.', 'auth-error');
                return;
            }

            if (changePassSubmitBtn) {
                changePassSubmitBtn.disabled = true;
                changePassSubmitBtn.textContent = 'Updating...';
            }
            showAuthMessage(changePassMsg, '', '');

            try {
                const response = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });

                const data = await response.json().catch(() => ({}));

                if (response.ok && data.success) {
                    showAuthMessage(changePassMsg, 'Password updated successfully!', 'auth-success');
                    changePasswordForm.reset();
                    setTimeout(() => {
                        if (accountModal) accountModal.classList.add('hidden');
                        showAuthMessage(changePassMsg, '', '');
                    }, 1400);
                } else {
                    showAuthMessage(changePassMsg, data.detail || 'Failed to update password.', 'auth-error');
                }
            } catch (err) {
                showAuthMessage(changePassMsg, 'Network error while updating password.', 'auth-error');
            } finally {
                if (changePassSubmitBtn) {
                    changePassSubmitBtn.disabled = false;
                    changePassSubmitBtn.textContent = 'Update Password';
                }
            }
        });
    }

    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (err) {
                console.error('Logout error:', err);
            }
            if (accountModal) accountModal.classList.add('hidden');
            enableLoginMode();
        });
    }
});
