// BartoloVPN Main JavaScript Application

// Global variables
let currentUser = null;
let isLoggedIn = false;
let toastsContainer = null;

// Basic HTML escaping for values rendered via innerHTML (e.g. DNS domain
// names, which come from DNS queries and shouldn't be trusted verbatim)
function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

// Toast notifications
function showToast(message, type = 'info', timeout = 3000) {
    if (!toastsContainer) {
        toastsContainer = document.createElement('div');
        toastsContainer.id = 'toasts';
        toastsContainer.style.position = 'fixed';
        toastsContainer.style.top = '1rem';
        toastsContainer.style.right = '1rem';
        toastsContainer.style.zIndex = '9999';
        document.body.appendChild(toastsContainer);
    }
    const toast = document.createElement('div');
    toast.textContent = message;
    toast.style.padding = '0.75rem 1rem';
    toast.style.marginBottom = '0.5rem';
    toast.style.borderRadius = '6px';
    toast.style.fontSize = '0.875rem';
    toast.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
    toast.style.backdropFilter = 'blur(6px)';
    toast.style.border = '1px solid rgba(255,255,255,0.1)';
    const colors = {
        info: ['#3b82f6', '#1e3a8a'],
        success: ['#10b981', '#065f46'],
        error: ['#ef4444', '#991b1b'],
        warning: ['#f59e0b', '#78350f']
    };
    const [c1, c2] = colors[type] || colors.info;
    toast.style.background = `linear-gradient(135deg, ${c1}, ${c2})`;
    toast.style.color = 'white';
    toastsContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity .4s';
        setTimeout(() => toast.remove(), 400);
    }, timeout);
}

// Attempt access token refresh
async function attemptTokenRefresh() {
    const refreshToken = localStorage.getItem('refreshToken');
    if (!refreshToken) return false;
    try {
        const resp = await fetch('/api/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
        if (!resp.ok) return false;
        const data = await resp.json();
        if (data.access_token) {
            localStorage.setItem('authToken', data.access_token);
            showToast('Session refreshed', 'info', 1500);
            return true;
        }
    } catch (e) {
        console.error('Token refresh failed', e);
    }
    return false;
}

// Unified authenticated fetch with 401 handling and refresh retry
async function apiFetch(url, options = {}) {
    const token = localStorage.getItem('authToken');
    const headers = Object.assign({}, options.headers || {}, {
        'Content-Type': 'application/json',
    });
    if (token) headers['Authorization'] = `Bearer ${token}`;
    let response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
        const refreshed = await attemptTokenRefresh();
        if (refreshed) {
            const newToken = localStorage.getItem('authToken');
            if (newToken) headers['Authorization'] = `Bearer ${newToken}`;
            response = await fetch(url, { ...options, headers });
        }
        if (response.status === 401) {
            showToast('Session expired. Please login again.', 'warning');
            handleLogout();
            throw new Error('Unauthorized');
        }
    }
    return response;
}

// DOM elements (will be initialized after DOM loads)
let loginScreen, dashboard, loginForm, registerForm, toggleForm, toggleText, toggleButtonText, loginError, registerError;

// Form toggle functionality
function toggleLoginRegister() {
    const isLoginVisible = loginForm.style.display !== 'none';
    
    if (isLoginVisible) {
        // Switch to registration form
        loginForm.style.display = 'none';
        registerForm.style.display = 'block';
        toggleText.textContent = 'Already have an account?';
        toggleButtonText.textContent = 'Login';
        loginError.textContent = '';
    } else {
        // Switch to login form
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
        toggleText.textContent = "Don't have an account?";
        toggleButtonText.textContent = 'Register';
        registerError.textContent = '';
    }
}

// Login functionality
async function handleLogin(event) {
    event.preventDefault();
    
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    // Show loading state
    const loginButton = document.getElementById('login-button') || event.submitter || loginForm.querySelector('button[type="submit"]');
    const originalText = loginButton ? loginButton.textContent : '';
    if (loginButton) {
        loginButton.textContent = 'Logging in...';
        loginButton.disabled = true;
    }
    loginError.textContent = '';
    
    try {
        const response = await apiFetch('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Show success message
            loginError.style.color = 'green';
            loginError.textContent = 'Login successful! Loading dashboard...';
            showToast('Logged in', 'success');

            // Store tokens
            localStorage.setItem('authToken', data.access_token);
            if (data.refresh_token) {
                localStorage.setItem('refreshToken', data.refresh_token);
            }
            currentUser = { username: data.username };
            isLoggedIn = true;
            
            // Show dashboard as SPA instead of redirecting
            setTimeout(() => {
                console.debug('Showing dashboard (SPA mode)');
                showDashboard();
            }, 250);
        } else {
            loginError.style.color = 'red';
            // API provides {'error': 'Invalid credentials'} in our backend
            const msg = data.error || data.detail || (response.status === 401 ? 'Invalid username or password' : 'Login failed');
            loginError.textContent = msg;
            showToast(msg, 'error');
        }
    } catch (error) {
        console.error('Login error:', error);
        loginError.style.color = 'red';
        loginError.textContent = 'Network error. Please try again.';
        showToast('Network error during login', 'error');
    } finally {
        // Reset button state
        if (loginButton) {
            loginButton.textContent = originalText;
            loginButton.disabled = false;
        }
    }
}

// Logout functionality (unified)
async function handleLogout() {
    console.log('Logout function called');
    const refreshToken = localStorage.getItem('refreshToken');
    // Clear tokens optimistically
    localStorage.removeItem('authToken');
    localStorage.removeItem('refreshToken');
    currentUser = null;
    isLoggedIn = false;
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
    } catch (e) {
        console.warn('Logout request failed (ignored):', e);
    }
    showToast('Logged out', 'info');
    // Redirect to root which serves login screen
    window.location.replace('/login');
}

// Registration functionality
async function handleRegister(event) {
    event.preventDefault();
    
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const confirmPassword = document.getElementById('reg-confirm-password').value;
    
    // Validate passwords match
    if (password !== confirmPassword) {
        registerError.textContent = 'Passwords do not match';
        return;
    }
    
    // Validate password strength
    if (password.length < 8) {
        registerError.textContent = 'Password must be at least 8 characters long';
        return;
    }
    
    try {
        const response = await apiFetch('/api/auth/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password }),
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Show success message
            registerError.style.color = 'green';
            registerError.textContent = 'Registration successful! Please login.';
            showToast('Registration successful – please login', 'success');
            
            // Switch to login form after a delay
            setTimeout(() => {
                toggleLoginRegister();
            }, 2000);
            document.getElementById('username').value = username;
            loginError.textContent = 'Registration successful! Please login.';
        } else {
            registerError.textContent = data.detail || 'Registration failed';
        }
    } catch (error) {
        console.error('Registration error:', error);
        registerError.textContent = 'Network error. Please try again.';
    }
}

// Show dashboard
function showDashboard() {
    console.log('showDashboard called');
    console.log('loginScreen:', loginScreen);
    console.log('dashboard:', dashboard);
    
    if (loginScreen) {
        loginScreen.style.display = 'none';
        loginScreen.classList.add('hidden');
        console.log('Login screen hidden');
    }
    
    if (dashboard) {
        dashboard.style.display = 'block';
        dashboard.classList.remove('hidden');
        console.log('Dashboard shown');
    }
    
    // Update user info
    if (currentUser) {
        const currentUserElement = document.getElementById('current-user');
        if (currentUserElement) {
            currentUserElement.textContent = currentUser.username;
            console.log('User info updated:', currentUser.username);
        }
    }
    
    // Load dashboard data
    loadDashboardData();
}

// Show login screen
function showLogin() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('refreshToken');
    currentUser = null;
    isLoggedIn = false;
    window.location.replace('/login');
}

// Load dashboard data
async function loadDashboardData() {
    try {
        const token = localStorage.getItem('authToken');
        if (!token) {
            showLogin();
            return;
        }
        
        // Load system status
    const statusResponse = await apiFetch('/api/system/stats');
        
        if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            updateSystemStatus(statusData);
        }
        
        // Load other dashboard data...
        
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    }
}

// Update system status
function updateSystemStatus(data) {
    console.log('Updating system status with data:', data);
    
    // Update system status
    const systemStatus = document.getElementById('system-status');
    if (systemStatus && data.system) {
        systemStatus.textContent = data.system.status || 'Unknown';
        systemStatus.className = `stat-value ${data.system.status === 'online' ? 'status-healthy' : 'status-warning'}`;
    }
    
    // Update VPN service statuses. The backend's "running" here just means
    // the service is deployed/configured, not a live health check (that's
    // what the per-protocol page's own status dot and the Monitoring page's
    // real connection counts are for) - "Installed" says what's actually
    // being reported instead of implying a live check that isn't happening.
    if (data.vpn) {
        for (const [protocol, elementId] of [['wireguard', 'wireguard-status'], ['openvpn', 'openvpn-status'], ['ikev2', 'ikev2-status']]) {
            const el = document.getElementById(elementId);
            const service = data.vpn[protocol];
            if (el && service) {
                const isRunning = service.status === 'running';
                el.textContent = isRunning ? 'Installed' : (service.status || 'Unknown');
                el.className = `stat-value ${isRunning ? 'status-healthy' : 'status-warning'}`;
            }
        }
    }

    // Each protocol page also has its own small status dot in its header
    // (separate DOM nodes from the Overview cards above, one per page).
    if (data.vpn) {
        for (const [protocol, elementId] of [['wireguard', 'wireguard-page-status'], ['openvpn', 'openvpn-page-status'], ['ikev2', 'ikev2-page-status']]) {
            const container = document.getElementById(elementId);
            const service = data.vpn[protocol];
            if (container && service) {
                const dot = container.querySelector('.status-dot');
                const text = container.querySelector('.status-text');
                const isRunning = service.status === 'running';
                if (dot) dot.className = `status-dot ${isRunning ? 'active' : 'inactive'}`;
                if (text) text.textContent = isRunning ? 'Installed' : (service.status || 'Unknown');
            }
        }
    }


    // Update network info
    if (data.bandwidth) {
        const bandwidthUsage = document.getElementById('bandwidth-usage');
        if (bandwidthUsage) {
            const sentMB = (data.bandwidth.sent / (1024 * 1024)).toFixed(1);
            const receivedMB = (data.bandwidth.received / (1024 * 1024)).toFixed(1);
            bandwidthUsage.textContent = `↑${sentMB} MB ↓${receivedMB} MB`;
        }
    }
    
    // Update active users
    const activeUsers = document.getElementById('active-users');
    if (activeUsers && data.users) {
        activeUsers.textContent = data.users.active || 0;
    }
    
    // Load system resources
    loadSystemResources();
}

// Enhanced Monitoring System with Real-time Updates
let monitoringInterval = null;
let autoRefreshEnabled = true;
let refreshIntervalMs = 10000; // 10 seconds default

async function loadSystemResources() {
    try {
        const response = await apiFetch('/api/system/resources');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        updateSystemResources(data);
        updateLastRefreshTime();
        updateSystemHealth(data);
    } catch (error) {
        console.error('Error loading system resources:', error);
        showSystemAlert('error', 'Failed to load system resources: ' + error.message);
    }
}

function updateSystemResources(data) {
    // Update CPU. cpu-progress/cpu-percent are the Overview page's bar+text;
    // cpu-usage/monitoring-cpu-progress are the Monitoring page's own
    // separate elements (previously both pages had colliding ids, so only
    // whichever was first in the DOM ever actually got updated).
    const cpuUsage = data.cpu?.usage || data.cpu_percent || 0;
    const cpuLoad = data.cpu?.load_average || 0;

    const cpuUsageEl = document.getElementById('cpu-usage');
    const cpuPercentEl = document.getElementById('cpu-percent');
    const cpuProgressEl = document.getElementById('cpu-progress');
    const monitoringCpuProgressEl = document.getElementById('monitoring-cpu-progress');
    const cpuLoadEl = document.getElementById('cpu-load');

    if (cpuUsageEl) cpuUsageEl.textContent = `${cpuUsage.toFixed(1)}%`;
    if (cpuPercentEl) cpuPercentEl.textContent = `${cpuUsage.toFixed(1)}%`;
    if (cpuProgressEl) cpuProgressEl.style.width = `${cpuUsage}%`;
    if (monitoringCpuProgressEl) monitoringCpuProgressEl.style.width = `${cpuUsage}%`;
    if (cpuLoadEl) cpuLoadEl.textContent = cpuLoad.toFixed(2);

    // Update Memory
    const memoryUsage = data.memory?.percent || data.memory_percent || 0;
    const memoryUsed = data.memory?.used_gb || data.memory_used_gb || 0;
    const memoryTotal = data.memory?.total_gb || data.memory_total_gb || 0;

    const memoryUsageEl = document.getElementById('memory-usage');
    const memoryPercentEl = document.getElementById('memory-percent');
    const memoryProgressEl = document.getElementById('memory-progress');
    const monitoringMemoryProgressEl = document.getElementById('monitoring-memory-progress');
    const memoryUsedEl = document.getElementById('memory-used');
    const memoryTotalEl = document.getElementById('memory-total');

    if (memoryUsageEl) memoryUsageEl.textContent = `${memoryUsage.toFixed(1)}%`;
    if (memoryPercentEl) memoryPercentEl.textContent = `${memoryUsage.toFixed(1)}%`;
    if (memoryProgressEl) memoryProgressEl.style.width = `${memoryUsage}%`;
    if (monitoringMemoryProgressEl) monitoringMemoryProgressEl.style.width = `${memoryUsage}%`;
    if (memoryUsedEl) memoryUsedEl.textContent = `${memoryUsed.toFixed(1)} GB`;
    if (memoryTotalEl) memoryTotalEl.textContent = `${memoryTotal.toFixed(1)} GB`;

    // Update Disk
    const diskUsage = data.disk?.percent || data.disk_percent || 0;
    const diskUsed = data.disk?.used_gb || data.disk_used_gb || 0;
    const diskTotal = data.disk?.total_gb || data.disk_total_gb || 0;

    const diskUsageEl = document.getElementById('disk-usage');
    const diskPercentEl = document.getElementById('disk-percent');
    const diskProgressEl = document.getElementById('disk-progress');
    const monitoringDiskProgressEl = document.getElementById('monitoring-disk-progress');
    const diskUsedEl = document.getElementById('disk-used');
    const diskTotalEl = document.getElementById('disk-total');

    if (diskUsageEl) diskUsageEl.textContent = `${diskUsage.toFixed(1)}%`;
    if (diskPercentEl) diskPercentEl.textContent = `${diskUsage.toFixed(1)}%`;
    if (diskProgressEl) diskProgressEl.style.width = `${diskUsage}%`;
    if (monitoringDiskProgressEl) monitoringDiskProgressEl.style.width = `${diskUsage}%`;
    if (diskUsedEl) diskUsedEl.textContent = `${diskUsed.toFixed(1)} GB`;
    if (diskTotalEl) diskTotalEl.textContent = `${diskTotal.toFixed(1)} GB`;
    
    // Update Network
    const networkSpeed = data.network?.speed_mbps || 0;
    const networkSent = data.network?.bytes_sent_mb || 0;
    const networkReceived = data.network?.bytes_recv_mb || 0;
    
    const networkSpeedEl = document.getElementById('network-speed');
    const networkSentEl = document.getElementById('network-sent');
    const networkReceivedEl = document.getElementById('network-received');
    
    if (networkSpeedEl) networkSpeedEl.textContent = `${networkSpeed.toFixed(1)} MB/s`;
    if (networkSentEl) networkSentEl.textContent = `${networkSent.toFixed(1)} MB`;
    if (networkReceivedEl) networkReceivedEl.textContent = `${networkReceived.toFixed(1)} MB`;
    
    // Update VPN Performance (if available)
    updateVPNMetrics(data.vpn || {});
}

function updateVPNMetrics(vpnData) {
    // WireGuard metrics
    const wgData = vpnData.wireguard || {};
    const wgConnectionsEl = document.getElementById('wg-connections');
    const wgBandwidthEl = document.getElementById('wg-bandwidth');
    const wgLatencyEl = document.getElementById('wg-latency');
    const wgTransferEl = document.getElementById('wg-transfer');
    
    if (wgConnectionsEl) wgConnectionsEl.textContent = wgData.connections || 0;
    if (wgBandwidthEl) wgBandwidthEl.textContent = `${(wgData.bandwidth || 0).toFixed(1)} MB/s`;
    if (wgLatencyEl) wgLatencyEl.textContent = `${wgData.latency || 0}ms`;
    if (wgTransferEl) wgTransferEl.textContent = `${(wgData.transfer || 0).toFixed(1)} MB`;
    updateProtocolStatus('wg', wgData.active || false);
    
    // OpenVPN metrics
    const ovpnData = vpnData.openvpn || {};
    const ovpnConnectionsEl = document.getElementById('ovpn-connections');
    const ovpnBandwidthEl = document.getElementById('ovpn-bandwidth');
    const ovpnLatencyEl = document.getElementById('ovpn-latency');
    const ovpnTransferEl = document.getElementById('ovpn-transfer');
    
    if (ovpnConnectionsEl) ovpnConnectionsEl.textContent = ovpnData.connections || 0;
    if (ovpnBandwidthEl) ovpnBandwidthEl.textContent = `${(ovpnData.bandwidth || 0).toFixed(1)} MB/s`;
    if (ovpnLatencyEl) ovpnLatencyEl.textContent = `${ovpnData.latency || 0}ms`;
    if (ovpnTransferEl) ovpnTransferEl.textContent = `${(ovpnData.transfer || 0).toFixed(1)} MB`;
    updateProtocolStatus('ovpn', ovpnData.active || false);
    
    // IKEv2 metrics
    const ikev2Data = vpnData.ikev2 || {};
    const ikev2ConnectionsEl = document.getElementById('ikev2-monitoring-connections');
    const ikev2PageConnectionsEl = document.getElementById('ikev2-connections');
    const ikev2BandwidthEl = document.getElementById('ikev2-bandwidth');
    const ikev2LatencyEl = document.getElementById('ikev2-latency');
    const ikev2TransferEl = document.getElementById('ikev2-transfer');

    if (ikev2ConnectionsEl) ikev2ConnectionsEl.textContent = ikev2Data.connections || 0;
    if (ikev2PageConnectionsEl) ikev2PageConnectionsEl.textContent = ikev2Data.connections || 0;
    if (ikev2BandwidthEl) ikev2BandwidthEl.textContent = `${(ikev2Data.bandwidth || 0).toFixed(1)} MB/s`;
    if (ikev2LatencyEl) ikev2LatencyEl.textContent = `${ikev2Data.latency || 0}ms`;
    if (ikev2TransferEl) ikev2TransferEl.textContent = `${(ikev2Data.transfer || 0).toFixed(1)} MB`;
    updateProtocolStatus('ikev2', ikev2Data.active || false);
    
    // Update total connections
    const totalConnections = (wgData.connections || 0) + (ovpnData.connections || 0) + (ikev2Data.connections || 0);
    const totalConnectionsEl = document.getElementById('total-vpn-connections');
    if (totalConnectionsEl) {
        totalConnectionsEl.textContent = `${totalConnections} Active Connection${totalConnections !== 1 ? 's' : ''}`;
    }
}

function updateProtocolStatus(protocol, isActive) {
    const statusDot = document.getElementById(`${protocol}-status-dot`);
    const statusText = document.getElementById(`${protocol}-status-text`);
    
    if (statusDot && statusText) {
        if (isActive) {
            statusDot.className = 'status-dot active';
            statusText.textContent = 'Active';
        } else {
            statusDot.className = 'status-dot inactive';
            statusText.textContent = 'Inactive';
        }
    }
}

function updateSystemHealth(data) {
    const healthDot = document.getElementById('system-health-dot');
    const healthText = document.getElementById('system-health-text');
    
    if (!healthDot || !healthText) return;
    
    const cpuUsage = data.cpu?.usage || data.cpu_percent || 0;
    const memoryUsage = data.memory?.percent || data.memory_percent || 0;
    const diskUsage = data.disk?.percent || data.disk_percent || 0;
    
    let status = 'healthy';
    let text = 'System Healthy';
    
    if (cpuUsage > 90 || memoryUsage > 90 || diskUsage > 95) {
        status = 'critical';
        text = 'Critical Usage';
        showSystemAlert('error', `High resource usage detected - CPU: ${cpuUsage.toFixed(1)}%, Memory: ${memoryUsage.toFixed(1)}%, Disk: ${diskUsage.toFixed(1)}%`);
    } else if (cpuUsage > 80 || memoryUsage > 80 || diskUsage > 85) {
        status = 'warning';
        text = 'High Usage';
        showSystemAlert('warning', `Elevated resource usage - CPU: ${cpuUsage.toFixed(1)}%, Memory: ${memoryUsage.toFixed(1)}%, Disk: ${diskUsage.toFixed(1)}%`);
    }
    
    healthDot.className = `status-dot ${status}`;
    healthText.textContent = text;
}

function updateLastRefreshTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString();
    const lastUpdateEl = document.getElementById('last-update-time');
    if (lastUpdateEl) lastUpdateEl.textContent = timeString;
}

function refreshAllMetrics() {
    loadSystemResources();
    loadActiveConnections();
}

function toggleAutoRefresh() {
    const checkbox = document.getElementById('auto-refresh-toggle');
    autoRefreshEnabled = checkbox ? checkbox.checked : true;
    
    if (autoRefreshEnabled) {
        startMonitoringInterval();
        showSystemAlert('info', 'Auto-refresh enabled');
    } else {
        stopMonitoringInterval();
        showSystemAlert('info', 'Auto-refresh disabled');
    }
}

function updateRefreshInterval() {
    const select = document.getElementById('refresh-interval');
    refreshIntervalMs = select ? parseInt(select.value) : 10000;
    
    if (autoRefreshEnabled) {
        stopMonitoringInterval();
        startMonitoringInterval();
    }
    
    const seconds = refreshIntervalMs / 1000;
    showSystemAlert('info', `Refresh interval updated to ${seconds} seconds`);
}

function startMonitoringInterval() {
    stopMonitoringInterval();
    if (autoRefreshEnabled) {
        monitoringInterval = setInterval(refreshAllMetrics, refreshIntervalMs);
    }
}

function stopMonitoringInterval() {
    if (monitoringInterval) {
        clearInterval(monitoringInterval);
        monitoringInterval = null;
    }
}

async function loadActiveConnections() {
    try {
        const response = await apiFetch('/api/system/connections');
        if (!response.ok) {
            // Connections endpoint might not exist, create dummy data
            updateConnectionsTable([]);
            return;
        }
        const connections = await response.json();
        updateConnectionsTable(connections);
    } catch (error) {
        console.error('Error loading active connections:', error);
        updateConnectionsTable([]);
    }
}

function updateConnectionsTable(connections) {
    const tbody = document.getElementById('active-connections-table');
    if (!tbody) return;
    
    if (connections.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center">No active connections</td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = connections.map(conn => `
        <tr data-protocol="${conn.protocol.toLowerCase()}">
            <td>${conn.username || 'Unknown'}</td>
            <td>
                <span class="protocol-badge ${conn.protocol.toLowerCase()}">${conn.protocol}</span>
            </td>
            <td>${conn.ip_address || 'N/A'}</td>
            <td>${conn.connected_since || 'N/A'}</td>
            <td>${conn.data_transfer || '0 MB'}</td>
            <td>
                <span class="status-badge ${conn.status.toLowerCase()}">${conn.status}</span>
            </td>
            <td>
                <button class="btn btn-sm btn-danger" onclick="disconnectClient('${conn.id}')">
                    <i class="fas fa-times"></i> Disconnect
                </button>
            </td>
        </tr>
    `).join('');
}

function filterConnections(protocol) {
    const rows = document.querySelectorAll('#active-connections-table tr[data-protocol]');
    const buttons = document.querySelectorAll('.filter-btn');
    
    // Update button states
    buttons.forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('data-filter') === protocol) {
            btn.classList.add('active');
        }
    });
    
    // Filter rows
    rows.forEach(row => {
        if (protocol === 'all' || row.getAttribute('data-protocol') === protocol) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

async function disconnectClient(clientId) {
    if (!confirm('Are you sure you want to disconnect this client?')) {
        return;
    }
    
    try {
        const response = await apiFetch(`/api/system/connections/${clientId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSystemAlert('success', 'Client disconnected successfully');
            loadActiveConnections();
        } else {
            throw new Error('Failed to disconnect client');
        }
    } catch (error) {
        console.error('Error disconnecting client:', error);
        showSystemAlert('error', 'Failed to disconnect client: ' + error.message);
    }
}

function showSystemAlert(type, message) {
    const alertsContainer = document.getElementById('system-alerts');
    if (!alertsContainer) return;
    
    // Remove placeholder if it exists
    const placeholder = alertsContainer.querySelector('.alert-placeholder');
    if (placeholder) {
        placeholder.remove();
    }
    
    const alertId = Date.now();
    const now = new Date().toLocaleTimeString();
    
    const alertHtml = `
        <div class="system-alert ${type}" id="alert-${alertId}">
            <div class="alert-content">
                <i class="fas fa-${getAlertIcon(type)}"></i>
                <span>${message}</span>
                <span class="alert-time">${now}</span>
            </div>
            <button class="alert-dismiss" onclick="dismissAlert('${alertId}')">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    alertsContainer.insertAdjacentHTML('afterbegin', alertHtml);
    
    // Auto-dismiss info and success alerts after 5 seconds
    if (type === 'info' || type === 'success') {
        setTimeout(() => dismissAlert(alertId), 5000);
    }
}

function getAlertIcon(type) {
    switch (type) {
        case 'success': return 'check-circle';
        case 'warning': return 'exclamation-triangle';
        case 'error': return 'exclamation-circle';
        case 'info':
        default: return 'info-circle';
    }
}

function dismissAlert(alertId) {
    const alert = document.getElementById(`alert-${alertId}`);
    if (alert) {
        alert.style.transition = 'all 0.3s ease';
        alert.style.opacity = '0';
        alert.style.transform = 'translateX(100%)';
        setTimeout(() => alert.remove(), 300);
    }
    
    // Show placeholder if no alerts remain
    const alertsContainer = document.getElementById('system-alerts');
    if (alertsContainer && alertsContainer.children.length === 0) {
        alertsContainer.innerHTML = `
            <div class="alert-placeholder">
                <i class="fas fa-check-circle text-success"></i>
                <span>No active alerts - System running normally</span>
            </div>
        `;
    }
}

function clearAllAlerts() {
    const alertsContainer = document.getElementById('system-alerts');
    if (alertsContainer) {
        alertsContainer.innerHTML = `
            <div class="alert-placeholder">
                <i class="fas fa-check-circle text-success"></i>
                <span>No active alerts - System running normally</span>
            </div>
        `;
    }
}

// Initialize monitoring when the monitoring tab is loaded
function initializeMonitoring() {
    console.log('Initializing monitoring dashboard...');
    
    // Load initial data
    refreshAllMetrics();
    
    // Start auto-refresh if enabled
    if (autoRefreshEnabled) {
        startMonitoringInterval();
    }
    
    // Show welcome alert
    setTimeout(() => {
        showSystemAlert('info', 'Monitoring dashboard initialized');
    }, 500);
}

// Stop monitoring when leaving the tab
function cleanupMonitoring() {
    stopMonitoringInterval();
}

// Fetch current authenticated user details
async function fetchCurrentUser() {
    try {
        const resp = await apiFetch('/api/auth/me');
        if (!resp.ok) return;
        const data = await resp.json();
        currentUser = { username: data.username, role: data.role };
        const el = document.getElementById('current-user');
        if (el) el.textContent = data.username;
    } catch (e) {
        console.error('Failed to fetch current user', e);
    }
}

// (Removed obsolete second handleLogout definition)

// Tab switching functionality
function switchTab(tabName) {
    console.log('Switching to tab:', tabName);
    
    // Hide all tab content
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => {
        content.style.display = 'none';
        content.classList.remove('active');
    });
    
    // Remove active class from all nav items
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.classList.remove('active');
    });
    
    // Show selected tab (using correct ID format)
    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        selectedTab.style.display = 'block';
        selectedTab.classList.add('active');
        console.log('Tab shown:', tabName);
    } else {
        console.error('Tab not found:', tabName);
    }
    
    // Add active class to selected nav item
    const selectedNavItem = document.querySelector(`[data-tab="${tabName}"]`);
    if (selectedNavItem) {
        selectedNavItem.classList.add('active');
        console.log('Nav item activated:', tabName);
    } else {
        console.error('Nav item not found for tab:', tabName);
    }
    
    // Load data when specific tabs are opened
    if (tabName === 'wireguard') {
        loadWireguardPeers();
        loadDashboardData();
        loadRegions();
    } else if (tabName === 'users') {
        loadUsers();
    } else if (tabName === 'openvpn') {
        loadOpenVPNClients();
        loadDashboardData();
    } else if (tabName === 'monitoring') {
        initializeMonitoring();
    } else if (tabName === 'activity') {
        loadDnsActivity();
    } else if (tabName === 'ikev2') {
        loadIkev2Credentials();
        loadDashboardData();
    } else if (tabName === 'regions') {
        loadRegionsAdminTable();
    } else if (tabName === 'settings') {
        loadSettings();
    } else {
        // Stop monitoring when switching away from monitoring tab
        cleanupMonitoring();
    }
}

// ========== THEME TOGGLE ==========
// base.html sets data-theme on <html> before first paint (from
// localStorage) to avoid a flash; this just keeps the toggle icon in sync
// and persists changes.
function initThemeToggle() {
    const icon = document.getElementById('theme-toggle-icon');
    if (!icon) return;
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    icon.className = theme === 'light' ? 'fas fa-sun' : 'fas fa-moon';
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    initThemeToggle();
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing elements...');
    initThemeToggle();
    setupCustomSelect('oracle-region');
    setupCustomSelect('region-country-code');
    setupCustomSelect('oracle-add-region-country-code');
    initRegionCountryAutofill();

    // Initialize DOM elements
    loginScreen = document.getElementById('login-screen');
    dashboard = document.getElementById('dashboard');
    loginForm = document.getElementById('login-form');
    registerForm = document.getElementById('register-form');
    toggleForm = document.getElementById('toggle-form');
    toggleText = document.getElementById('toggle-text');
    toggleButtonText = document.getElementById('toggle-button-text');
    loginError = document.getElementById('login-error');
    registerError = document.getElementById('register-error');
    
    console.log('DOM elements initialized:', {
        loginScreen: !!loginScreen,
        dashboard: !!dashboard,
        loginForm: !!loginForm,
        registerForm: !!registerForm
    });
    
    // Check if user is already logged in
    const token = localStorage.getItem('authToken');
    if (token) {
        console.log('Token found, verifying and showing dashboard');
        // Try to fetch current user to verify token is valid
        fetchCurrentUser().then(() => {
            console.debug('Token verified, showing dashboard');
            showDashboard();
        }).catch(() => {
            console.debug('Token invalid, showing login');
            localStorage.removeItem('authToken');
            localStorage.removeItem('refreshToken');
            // Make sure dashboard is hidden and login is shown
            if (dashboard) dashboard.style.display = 'none';
            if (loginScreen) loginScreen.style.display = 'block';
        });
    } else {
        console.log('No token found, showing login screen...');
        // Make sure dashboard is hidden and login is shown
        if (dashboard) dashboard.style.display = 'none';
        if (loginScreen) loginScreen.style.display = 'block';
    }
    
    // Form event listeners
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
        console.log('Login form listener added');
    }
    
    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
        console.log('Register form listener added');
    }
    
    if (toggleForm) {
        toggleForm.addEventListener('click', toggleLoginRegister);
        console.log('Toggle form listener added');
    }
    
    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
        console.log('Logout button listener added');
    }
    
    // Tab navigation
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
    console.log('Tab navigation listeners added');
    
    // Add peer form listener
    const addPeerForm = document.getElementById('add-peer-form');
    if (addPeerForm) {
        addPeerForm.addEventListener('submit', handleAddPeer);
        console.log('Add peer form listener added');
    }

    // Add region form listener
    const addRegionForm = document.getElementById('add-region-form');
    if (addRegionForm) {
        addRegionForm.addEventListener('submit', handleAddRegion);
        console.log('Add region form listener added');
    }

    // Add via Oracle form listener
    const addOracleRegionForm = document.getElementById('add-oracle-region-form');
    if (addOracleRegionForm) {
        addOracleRegionForm.addEventListener('submit', handleAddOracleRegion);
    }
    
    // Edit peer form listener
    const editPeerForm = document.getElementById('edit-peer-form');
    if (editPeerForm) {
        editPeerForm.addEventListener('submit', handleEditPeer);
        console.log('Edit peer form listener added');
    }
    
    // Add user form listener
    const addUserForm = document.getElementById('add-user-form');
    if (addUserForm) {
        addUserForm.addEventListener('submit', handleAddUser);
        console.log('Add user form listener added');
    }
    
    // Add OpenVPN client form listener
    const addOpenVPNClientForm = document.getElementById('add-openvpn-client-form');
    if (addOpenVPNClientForm) {
        addOpenVPNClientForm.addEventListener('submit', handleAddOpenVPNClient);
        console.log('Add OpenVPN client form listener added');
    }
    
    // Add IKEv2 user form listener
    const addIKEv2UserForm = document.getElementById('add-ikev2-user-form');
    if (addIKEv2UserForm) {
        addIKEv2UserForm.addEventListener('submit', handleAddIKEv2User);
        console.log('Add IKEv2 user form listener added');
    }
    
    // Add mobile navigation event listeners
    const mobileNavItems = document.querySelectorAll('.nav-item');
    mobileNavItems.forEach(item => {
        item.addEventListener('click', closeMobileMenu);
    });
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', handleOutsideClick);
    
    // Close mobile menu on escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeMobileMenu();
        }
    });
    
    // Handle Edit User Form Submission
    const editUserForm = document.getElementById('edit-user-form');
    if (editUserForm) {
        editUserForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const userId = document.getElementById('edit-user-id').value;
            const formData = new FormData(editUserForm);
            
            // Get selected protocols
            const protocols = [];
            const protocolCheckboxes = document.querySelectorAll('input[name="edit-user-protocols"]:checked');
            protocolCheckboxes.forEach(checkbox => {
                protocols.push(checkbox.value);
            });
            
            // Prepare update data
            const updateData = {
                username: formData.get('edit-user-username'),
                email: formData.get('edit-user-email'),
                role: formData.get('edit-user-role'),
                status: formData.get('edit-user-status'),
                protocols: protocols
            };
            
            // Only include password if it's provided
            const password = formData.get('edit-user-password');
            if (password && password.trim() !== '') {
                updateData.password = password;
            }
            
            try {
                const response = await apiFetch(`/api/users/${userId}`, {
                    method: 'PUT',
                    body: JSON.stringify(updateData)
                });
                
                if (response.ok) {
                    showToast('User updated successfully', 'success');
                    closeEditUserModal();
                    loadUsers(); // Refresh the user list
                } else {
                    const errorData = await response.json();
                    showToast(errorData.detail || 'Failed to update user', 'error');
                }
            } catch (error) {
                console.error('Error updating user:', error);
                showToast('Failed to update user', 'error');
            }
        });
        console.log('Edit user form listener added');
    }
    
    console.log('Mobile navigation listeners added');
});

// WireGuard Modal Functions
function showAddPeerModal() {
    console.log('Showing Add Peer modal');
    const modal = document.getElementById('add-peer-modal');
    if (modal) {
        modal.style.display = 'flex';
        // Clear form
        const form = document.getElementById('add-peer-form');
        if (form) form.reset();
        loadRegions();
    } else {
        console.error('Add peer modal not found');
    }
}

// Populate the region <select> in the Add Peer modal from /regions -
// unlike the OpenVPN tab's hardcoded DNS-region dropdown, these are real,
// DB-backed server locations, so they're fetched fresh each time.
async function loadRegions() {
    const select = document.getElementById('peer-region');
    if (!select) return;
    try {
        const response = await apiFetch('/regions');
        if (!response.ok) return;
        const regions = await response.json();
        const currentValue = select.value;
        select.innerHTML = regions
            .filter(r => r.is_active)
            .map(r => `<option value="${escapeHtml(r.slug)}">${escapeHtml(r.display_name)}${r.is_local ? '' : ' (' + escapeHtml(r.country_code) + ')'}</option>`)
            .join('');
        if (currentValue && regions.some(r => r.slug === currentValue)) {
            select.value = currentValue;
        }
    } catch (error) {
        console.error('Error loading regions:', error);
    }
}

function closeAddPeerModal() {
    console.log('Closing Add Peer modal');
    const modal = document.getElementById('add-peer-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Edit peer functionality. region is immutable once a peer is created
// (moving it to a different server means delete+recreate elsewhere), so
// the edit form doesn't expose a region selector - it just needs to
// remember which region this peer lives on, to route the config-fetch,
// update, and later delete calls to the right place.
async function editPeer(peerName, region = 'local') {
    console.log('Edit peer called with peerName:', peerName, 'region:', region);

    try {
        // Read the peer's actual saved config so the form starts from its
        // real current AllowedIPs, not a hardcoded guess.
        let allowedIPs = '0.0.0.0/0';
        const configResponse = await apiFetch(`/vpn/wireguard/peers/${peerName}/config?region=${encodeURIComponent(region)}`);
        if (configResponse.ok) {
            const configText = await configResponse.text();
            const match = configText.match(/^AllowedIPs\s*=\s*(.+)$/m);
            if (match) allowedIPs = match[1].trim();
        }

        document.getElementById('edit-peer-current-name').value = peerName;
        document.getElementById('edit-peer-region').value = region;
        document.getElementById('edit-peer-name').value = peerName;
        document.getElementById('edit-peer-allowed-ips').value = allowedIPs;

        const modal = document.getElementById('edit-peer-modal');
        if (modal) {
            modal.style.display = 'block';
            console.log('Edit peer modal shown');
        } else {
            console.error('Edit peer modal not found');
        }

    } catch (error) {
        console.error('Error loading peer data:', error);
        showToast('Failed to load peer data', 'error');
    }
}

function closeEditPeerModal() {
    console.log('Closing Edit Peer modal');
    const modal = document.getElementById('edit-peer-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function handleAddPeer(event) {
    event.preventDefault();
    console.log('Adding new WireGuard peer');
    
    const formData = new FormData(event.target);
    const peerData = {
        peer_name: formData.get('peer-name'),
        user_id: 1, // TODO: Get current user ID from token
        allowed_ips: formData.get('peer-allowed-ips') || "0.0.0.0/0",
        region: formData.get('peer-region') || 'local'
    };
    
    try {
        const response = await apiFetch('/vpn/wireguard/peers', {
            method: 'POST',
            body: JSON.stringify(peerData)
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast('Peer added successfully', 'success');
            closeAddPeerModal();
            // Reset form
            event.target.reset();
            // Reload peers table
            loadWireguardPeers();
            // Show the QR code right away so it can be scanned with the
            // WireGuard mobile app (iOS/Android)
            if (result.qr_code) {
                showPeerQrModal(result.qr_code, result.peer_name);
            }
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to add peer', 'error');
        }
    } catch (error) {
        console.error('Error adding peer:', error);
        showToast('Error adding peer', 'error');
    }
}

// Show the QR-code modal for a given base64-encoded PNG
function showPeerQrModal(qrCodeBase64, peerName) {
    const modal = document.getElementById('peer-qr-modal');
    const img = document.getElementById('peer-qr-image');
    const nameEl = document.getElementById('peer-qr-name');
    const suggestedNameEl = document.getElementById('peer-qr-suggested-name');
    if (!modal || !img) {
        console.error('QR modal not found');
        return;
    }
    img.src = `data:image/png;base64,${qrCodeBase64}`;
    if (nameEl) nameEl.textContent = peerName || '';
    if (suggestedNameEl) suggestedNameEl.textContent = peerName ? `BartoloVPN-${peerName}` : '';
    modal.style.display = 'flex';
}

function closePeerQrModal() {
    const modal = document.getElementById('peer-qr-modal');
    if (modal) modal.style.display = 'none';
}

// Fetch and show the QR code for an already-existing peer
async function showPeerQr(peerName, region = 'local') {
    try {
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}/qrcode?region=${encodeURIComponent(region)}`);
        if (response.ok) {
            const data = await response.json();
            showPeerQrModal(data.qr_code, data.peer_name);
        } else {
            showToast('Failed to load QR code', 'error');
        }
    } catch (error) {
        console.error('Error loading QR code:', error);
        showToast('Error loading QR code', 'error');
    }
}

async function handleEditPeer(event) {
    event.preventDefault();
    console.log('Editing WireGuard peer');
    
    const formData = new FormData(event.target);
    const currentName = formData.get('current-name');
    const newName = formData.get('peer-name');
    const allowedIPs = formData.get('peer-allowed-ips') || "0.0.0.0/0";
    const region = formData.get('region') || 'local';

    try {
        const response = await apiFetch(`/vpn/wireguard/peers/${currentName}?region=${encodeURIComponent(region)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ peer_name: newName, allowed_ips: allowedIPs })
        });

        const data = await response.json();
        if (response.ok) {
            showToast(`Peer updated successfully`, 'success');
            closeEditPeerModal();
            loadWireguardPeers();
        } else {
            showToast(`Failed to update peer: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error editing peer:', error);
        showToast('Error editing peer', 'error');
    }
}

async function loadWireguardPeers() {
    console.log('Loading WireGuard peers');
    try {
        const response = await apiFetch('/vpn/wireguard/peers');
        if (response.ok) {
            const data = await response.json();
            const peers = data.peers || [];
            const tableBody = document.getElementById('wireguard-peers-table');
            if (tableBody) {
                if (peers.length === 0) {
                    tableBody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center">No peers configured</td>
                        </tr>
                    `;
                } else {
                    tableBody.innerHTML = peers.map(peer => {
                        const region = peer.region || 'local';
                        const regionDisplay = peer.region_display || 'Local (this server)';
                        return `
                        <tr>
                            <td>${escapeHtml(peer.name)}</td>
                            <td>${escapeHtml(regionDisplay)}</td>
                            <td>
                                <div class="config-value-container inline">
                                    <span class="config-value masked" id="peer-key-${peer.name}" data-value="${peer.public_key || 'Not Available'}">••••••••••••••••••••••••••••••••••••••••••••••••••</span>
                                    <button class="toggle-visibility-btn small" onclick="toggleConfigVisibility('peer-key-${peer.name}')" title="Show/Hide Key">
                                        <i class="fas fa-eye"></i>
                                    </button>
                                    <button class="copy-btn small" onclick="copyConfigValue('peer-key-${peer.name}')" title="Copy Key">
                                        <i class="fas fa-copy"></i>
                                    </button>
                                </div>
                            </td>
                            <td>${peer.ip}</td>
                            <td><span class="status-badge status-active">Active</span></td>
                            <td>
                                <button class="btn btn-sm btn-secondary" onclick="editPeer('${peer.name}', '${region}')">
                                    <i class="fas fa-edit"></i> Edit
                                </button>
                                <button class="btn btn-sm btn-secondary" onclick="downloadPeerConfig('${peer.name}', '${region}')">
                                    <i class="fas fa-download"></i> Config
                                </button>
                                <button class="btn btn-sm btn-secondary" onclick="showPeerQr('${peer.name}', '${region}')">
                                    <i class="fas fa-qrcode"></i> QR
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="deletePeer('${peer.name}', '${region}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `;
                    }).join('');
                    console.log('WireGuard peer table updated with', peers.length, 'peers.');
                }
            }
            if (data.warnings && data.warnings.length) {
                data.warnings.forEach(w => showToast(w, 'warning', 6000));
            }
        } else {
            console.error('Failed to load peers');
            const tableBody = document.getElementById('wireguard-peers-table');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center text-danger">Failed to load peers</td>
                    </tr>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading peers:', error);
    }
}

// Load and render the DNS/domain Activity tab. Server paginates at 50
// rows/page, capped at 10 pages (500 rows) - see /api/dns/queries.
let dnsActivityPage = 1;
let dnsActivityTotalPages = 1;

async function loadDnsActivity(page) {
    if (typeof page === 'number') {
        dnsActivityPage = page;
    }
    console.log('Loading DNS activity, page', dnsActivityPage);
    const tableBody = document.getElementById('dns-activity-table');
    const peerFilter = document.getElementById('activity-peer-filter');
    const protocolFilter = document.getElementById('activity-protocol-filter');
    const selectedPeerIp = peerFilter ? peerFilter.value : '';
    const selectedProtocol = protocolFilter ? protocolFilter.value : '';

    try {
        const params = new URLSearchParams({ page: dnsActivityPage });
        if (selectedPeerIp) params.set('peer_ip', selectedPeerIp);
        if (selectedProtocol) params.set('protocol', selectedProtocol);

        const response = await apiFetch(`/api/dns/queries?${params.toString()}`);
        if (!response.ok) {
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Failed to load activity</td></tr>';
            }
            return;
        }
        const data = await response.json();
        const queries = data.queries || [];
        dnsActivityPage = data.page || 1;
        dnsActivityTotalPages = data.total_pages || 1;
        updateDnsActivityPagination();

        // Populate the peer filter dropdown with peers seen in the results,
        // without wiping out the user's current selection
        if (peerFilter) {
            const seen = new Map();
            queries.forEach(q => seen.set(q.peer_ip, q.peer_name));
            const currentValue = peerFilter.value;
            peerFilter.innerHTML = '<option value="">All peers/clients</option>' +
                Array.from(seen.entries()).map(([ip, name]) =>
                    `<option value="${escapeHtml(ip)}">${escapeHtml(name)}</option>`
                ).join('');
            peerFilter.value = currentValue;
        }

        if (!tableBody) return;

        if (queries.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="4" class="text-center">No DNS activity recorded yet</td></tr>';
            return;
        }

        tableBody.innerHTML = queries.map(q => `
            <tr>
                <td>${escapeHtml(new Date(q.timestamp + 'Z').toLocaleString())}</td>
                <td>${escapeHtml(q.peer_name)}</td>
                <td>${escapeHtml(q.protocol)}</td>
                <td>${escapeHtml(q.domain)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading DNS activity:', error);
        if (tableBody) {
            tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Error loading activity</td></tr>';
        }
    }
}

function updateDnsActivityPagination() {
    const indicator = document.getElementById('activity-page-indicator');
    const prevBtn = document.getElementById('activity-prev-page');
    const nextBtn = document.getElementById('activity-next-page');
    if (indicator) indicator.textContent = `Page ${dnsActivityPage} of ${dnsActivityTotalPages}`;
    if (prevBtn) prevBtn.disabled = dnsActivityPage <= 1;
    if (nextBtn) nextBtn.disabled = dnsActivityPage >= dnsActivityTotalPages;
}

function changeDnsActivityPage(delta) {
    const target = dnsActivityPage + delta;
    if (target < 1 || target > dnsActivityTotalPages) return;
    loadDnsActivity(target);
}

// Populate the IKEv2 tab's PSK/username/password with the real values
// (these used to be hardcoded placeholder text in the template)
async function loadIkev2Credentials() {
    console.log('Loading IKEv2 credentials');
    try {
        const response = await apiFetch('/vpn/ikev2/credentials');
        if (!response.ok) {
            console.error('Failed to load IKEv2 credentials');
            return;
        }
        const creds = await response.json();

        const pskEl = document.getElementById('ikev2-psk');
        if (pskEl) pskEl.setAttribute('data-value', creds.psk);

        document.querySelectorAll('[id$="-username"]').forEach(el => {
            if (el.classList.contains('masked')) {
                el.setAttribute('data-value', creds.username);
            } else {
                el.textContent = creds.username;
            }
        });

        document.querySelectorAll('[id$="-password"]').forEach(el => {
            if (el.classList.contains('masked')) {
                el.setAttribute('data-value', creds.password);
            } else {
                el.textContent = creds.password;
            }
        });
    } catch (error) {
        console.error('Error loading IKEv2 credentials:', error);
    }
}

// Download peer configuration file
async function downloadPeerConfig(peerName, region = 'local') {
    try {
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}/config?region=${encodeURIComponent(region)}`);
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${peerName}.conf`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showToast('Configuration downloaded successfully', 'success');
        } else {
            showToast('Failed to download configuration', 'error');
        }
    } catch (error) {
        console.error('Error downloading config:', error);
        showToast('Error downloading configuration', 'error');
    }
}

// Delete peer
async function deletePeer(peerName, region = 'local') {
    if (!confirm(`Are you sure you want to delete peer "${peerName}"?\n\nThis action cannot be undone and will remove the peer configuration.`)) {
        return;
    }

    try {
        console.log('Deleting peer:', peerName, 'region:', region);
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}?region=${encodeURIComponent(region)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast(`Peer "${peerName}" deleted successfully`, 'success');
            loadWireguardPeers(); // Refresh the peer list
        } else {
            const error = await response.json();
            showToast(`Failed to delete peer: ${error.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error deleting peer:', error);
        showToast('Failed to delete peer. Check console for details.', 'error');
    }
}

// ========== REGIONS MANAGEMENT ==========

function showAddRegionModal() {
    const modal = document.getElementById('add-region-modal');
    if (modal) {
        modal.style.display = 'flex';
        const form = document.getElementById('add-region-form');
        if (form) form.reset();
        // form.reset() resets the hidden <select>'s value but not the
        // custom dropdown's visible trigger label - sync it back manually.
        syncCustomSelectLabel('region-country-code');
    }
}

// Suggests Display Name/Slug from the picked country so the operator isn't
// typing both a name and a code by hand - only fills fields that are still
// empty, so it never clobbers something already typed.
function wireCountryAutofill(countrySelectId, displayNameId, cityId, slugId) {
    const countrySelect = document.getElementById(countrySelectId);
    if (!countrySelect) return;
    countrySelect.addEventListener('change', () => {
        const countryName = countrySelect.selectedOptions[0]?.textContent || '';
        const countryCode = countrySelect.value;
        if (!countryCode) return;

        const displayNameEl = document.getElementById(displayNameId);
        const cityEl = document.getElementById(cityId);
        const slugEl = document.getElementById(slugId);

        if (displayNameEl && !displayNameEl.value) {
            const city = cityEl ? cityEl.value.trim() : '';
            displayNameEl.value = city ? `${countryName} - ${city}` : countryName;
        }
        if (slugEl && !slugEl.value) {
            slugEl.value = countryCode.toLowerCase();
        }
    });
}

function initRegionCountryAutofill() {
    wireCountryAutofill('region-country-code', 'region-display-name', 'region-city', 'region-slug');
    wireCountryAutofill(
        'oracle-add-region-country-code', 'oracle-add-region-display-name',
        'oracle-add-region-city', 'oracle-add-region-slug'
    );
}

function closeAddRegionModal() {
    const modal = document.getElementById('add-region-modal');
    if (modal) modal.style.display = 'none';
}

async function handleAddRegion(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const regionData = {
        slug: formData.get('region-slug'),
        display_name: formData.get('region-display-name'),
        country_code: formData.get('region-country-code'),
        city: formData.get('region-city') || null,
        agent_url: formData.get('region-agent-url'),
        agent_key: formData.get('region-agent-key'),
        wireguard_endpoint_host: formData.get('region-wg-host'),
        wireguard_endpoint_port: parseInt(formData.get('region-wg-port'), 10) || 51820
    };

    try {
        const response = await apiFetch('/regions', {
            method: 'POST',
            body: JSON.stringify(regionData)
        });
        const data = await response.json();
        if (response.ok) {
            showToast(`Region "${data.display_name}" added successfully`, 'success');
            closeAddRegionModal();
            event.target.reset();
            loadRegionsAdminTable();
            loadRegions();
        } else {
            showToast(data.detail || 'Failed to add region', 'error');
        }
    } catch (error) {
        console.error('Error adding region:', error);
        showToast('Error adding region', 'error');
    }
}

function showAddOracleRegionModal() {
    const modal = document.getElementById('add-oracle-region-modal');
    if (modal) {
        modal.style.display = 'flex';
        const form = document.getElementById('add-oracle-region-form');
        if (form) form.reset();
        syncCustomSelectLabel('oracle-add-region-country-code');
    }
}

function closeAddOracleRegionModal() {
    const modal = document.getElementById('add-oracle-region-modal');
    if (modal) modal.style.display = 'none';
}

async function handleAddOracleRegion(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const regionData = {
        slug: formData.get('oracle-add-region-slug'),
        display_name: formData.get('oracle-add-region-display-name'),
        country_code: formData.get('oracle-add-region-country-code'),
        city: formData.get('oracle-add-region-city') || null,
        wireguard_port: parseInt(formData.get('oracle-add-region-wg-port'), 10) || 51820
    };

    const submitBtn = document.getElementById('add-oracle-region-submit');
    if (submitBtn) submitBtn.disabled = true;

    try {
        const response = await apiFetch('/regions/oracle', {
            method: 'POST',
            body: JSON.stringify(regionData)
        });
        const data = await response.json();
        if (response.ok) {
            showToast(`Creating "${data.display_name}" on Oracle Cloud - this takes several minutes`, 'success');
            closeAddOracleRegionModal();
            event.target.reset();
            loadRegionsAdminTable();
            loadRegions();
            startProvisioningPoll();
        } else {
            showToast(data.detail || 'Failed to create Oracle region', 'error');
        }
    } catch (error) {
        console.error('Error creating Oracle region:', error);
        showToast('Error creating Oracle region', 'error');
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

// Polls the regions table while any region is still "provisioning" -
// creating an Oracle instance takes several minutes (Docker install,
// image build, first TLS cert), so the operator needs the table to
// update itself rather than requiring a manual refresh. Stops itself
// once nothing is left provisioning.
let provisioningPollTimer = null;

function startProvisioningPoll() {
    if (provisioningPollTimer) return;
    provisioningPollTimer = setInterval(async () => {
        try {
            const response = await apiFetch('/regions');
            if (!response.ok) return;
            const regions = await response.json();
            const stillProvisioning = regions.some(r => r.health_status === 'provisioning');
            loadRegionsAdminTable();
            loadRegions();
            if (!stillProvisioning) {
                clearInterval(provisioningPollTimer);
                provisioningPollTimer = null;
            }
        } catch (error) {
            console.error('Error polling region provisioning status:', error);
        }
    }, 15000);
}

async function loadRegionsAdminTable() {
    const tableBody = document.getElementById('regions-table');
    if (!tableBody) return;
    try {
        const response = await apiFetch('/regions');
        if (!response.ok) {
            tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Failed to load regions</td></tr>';
            return;
        }
        const regions = await response.json();
        if (regions.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="6" class="text-center">No regions configured</td></tr>';
            return;
        }
        tableBody.innerHTML = regions.map(r => {
            // country_code isn't a real, known value for the local server
            // (it's just a hardcoded "US" placeholder in create_default_region,
            // not derived from any actual IP geolocation) - only show it for
            // real remote regions, where the operator actually chose it.
            const location = r.is_local
                ? r.display_name
                : (r.city ? `${r.display_name} (${r.city}, ${r.country_code})` : `${r.display_name} (${r.country_code})`);
            const healthClass = r.health_status === 'healthy' ? 'status-active'
                : r.health_status === 'provisioning' ? 'status-provisioning'
                : 'status-inactive';
            const lastChecked = r.last_health_check ? new Date(r.last_health_check + 'Z').toLocaleString() : 'Never';
            const actions = r.is_local
                ? '<span class="form-help">Local server - not editable</span>'
                : `
                    <button class="btn btn-sm btn-secondary" onclick="testRegionHealth(${r.id})">
                        <i class="fas fa-heartbeat"></i> Check
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteRegion(${r.id}, '${escapeHtml(r.slug)}')">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                `;
            return `
                <tr>
                    <td>${escapeHtml(location)}</td>
                    <td>${escapeHtml(r.slug)}</td>
                    <td><span class="status-badge ${healthClass}">${escapeHtml(r.health_status)}</span></td>
                    <td>${r.peer_count}</td>
                    <td>${escapeHtml(lastChecked)}</td>
                    <td>${actions}</td>
                </tr>
            `;
        }).join('');
        if (regions.some(r => r.health_status === 'provisioning')) startProvisioningPoll();
    } catch (error) {
        console.error('Error loading regions table:', error);
        tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Error loading regions</td></tr>';
    }
}

async function testRegionHealth(regionId) {
    try {
        const response = await apiFetch(`/regions/${regionId}/health-check`, { method: 'POST' });
        const data = await response.json();
        if (response.ok) {
            showToast(`Region "${data.display_name}" is ${data.health_status}`, data.health_status === 'healthy' ? 'success' : 'warning');
            loadRegionsAdminTable();
        } else {
            showToast(data.detail || 'Health check failed', 'error');
        }
    } catch (error) {
        console.error('Error checking region health:', error);
        showToast('Error checking region health', 'error');
    }
}

async function deleteRegion(regionId, slug) {
    if (!confirm(`Are you sure you want to delete region "${slug}"?\n\nExisting peers on that server are not affected, but the dashboard will stop being able to manage them.`)) {
        return;
    }
    try {
        const response = await apiFetch(`/regions/${regionId}`, { method: 'DELETE' });
        const data = await response.json();
        if (response.ok) {
            showToast(`Region "${slug}" deleted`, 'success');
            loadRegionsAdminTable();
            loadRegions();
        } else if (response.status === 409) {
            if (confirm(`${data.detail}\n\nDelete anyway?`)) {
                const forceResponse = await apiFetch(`/regions/${regionId}?force=true`, { method: 'DELETE' });
                if (forceResponse.ok) {
                    showToast(`Region "${slug}" deleted`, 'success');
                    loadRegionsAdminTable();
                    loadRegions();
                } else {
                    showToast('Failed to delete region', 'error');
                }
            }
        } else {
            showToast(data.detail || 'Failed to delete region', 'error');
        }
    } catch (error) {
        console.error('Error deleting region:', error);
        showToast('Error deleting region', 'error');
    }
}

// ========== SETTINGS ==========

async function loadSettings() {
    try {
        const response = await apiFetch('/settings');
        if (!response.ok) {
            showToast('Failed to load settings', 'error');
            return;
        }
        const s = await response.json();

        const serverIpEl = document.getElementById('server-ip');
        if (serverIpEl) serverIpEl.value = s.server_ip || '';
        const domainEl = document.getElementById('domain');
        if (domainEl) domainEl.value = s.domain || '';

        setValueIfPresent('timezone', s.timezone);
        setValueIfPresent('dns-servers', s.dns_servers);
        setValueIfPresent('encryption-level', String(s.encryption_level));
        setCheckedIfPresent('kill-switch', s.kill_switch_enabled);
        setValueIfPresent('log-level', s.log_level);
        setValueIfPresent('log-retention', s.log_retention_days);

        setCheckedIfPresent('oracle-enabled', s.oracle_enabled);
        setValueIfPresent('oracle-tenancy-ocid', s.oracle_tenancy_ocid);
        setValueIfPresent('oracle-user-ocid', s.oracle_user_ocid);
        setValueIfPresent('oracle-fingerprint', s.oracle_fingerprint);
        setValueIfPresent('oracle-region', s.oracle_region);
        syncCustomSelectLabel('oracle-region');

        const apiKeyStatus = document.getElementById('oracle-api-key-status');
        if (apiKeyStatus) {
            apiKeyStatus.innerHTML = s.oracle_api_key_configured
                ? '<i class="fas fa-circle-check"></i> A key is stored.'
                : '<i class="fas fa-circle-xmark"></i> No key stored yet.';
        }

        await loadOracleSshKeys(s.oracle_ssh_key_name);
        await loadOracleApiKeyStatus();
        toggleOracleSettings();
    } catch (error) {
        console.error('Error loading settings:', error);
        showToast('Error loading settings', 'error');
    }
}

function setValueIfPresent(elementId, value) {
    const el = document.getElementById(elementId);
    if (el && value !== null && value !== undefined) el.value = value;
}

function setCheckedIfPresent(elementId, value) {
    const el = document.getElementById(elementId);
    if (el && value !== null && value !== undefined) el.checked = value;
}

// Renders a custom-styled dropdown driven by a hidden <select>, since Linux
// Chrome renders a native <select>'s open popup outside CSS's reach (see
// the comment in settings.html above #oracle-region-dropdown). The hidden
// select stays the single source of truth for options and value - existing
// getValue()/setValueIfPresent() calls on its id keep working unchanged.
// Wire up once per page load (elements persist across tab switches, so
// calling this again would stack duplicate listeners); call
// syncCustomSelectLabel() after anything sets the select's value
// programmatically (e.g. loadSettings) to keep the visible label in sync.
function setupCustomSelect(selectId) {
    const select = document.getElementById(selectId);
    const dropdown = document.getElementById(`${selectId}-dropdown`);
    const trigger = document.getElementById(`${selectId}-trigger`);
    const panel = document.getElementById(`${selectId}-panel`);
    const label = document.getElementById(`${selectId}-trigger-label`);
    if (!select || !dropdown || !trigger || !panel || !label) return;

    const placeholder = label.textContent;

    panel.innerHTML = '';
    Array.from(select.children).forEach(child => {
        if (child.tagName === 'OPTGROUP') {
            const groupLabel = document.createElement('div');
            groupLabel.className = 'custom-dropdown-optgroup-label';
            groupLabel.textContent = child.label;
            panel.appendChild(groupLabel);
            Array.from(child.children).forEach(opt => panel.appendChild(buildCustomOption(opt)));
        } else if (child.tagName === 'OPTION' && child.value) {
            panel.appendChild(buildCustomOption(child));
        }
    });

    function buildCustomOption(opt) {
        const item = document.createElement('div');
        item.className = 'custom-dropdown-option';
        item.textContent = opt.textContent;
        item.dataset.value = opt.value;
        item.addEventListener('click', () => {
            select.value = opt.value;
            select.dispatchEvent(new Event('change'));
            syncCustomSelectLabel(selectId);
            closePanel();
        });
        return item;
    }

    function openPanel() {
        panel.hidden = false;
        trigger.classList.add('open');
    }

    function closePanel() {
        panel.hidden = true;
        trigger.classList.remove('open');
    }

    trigger.addEventListener('click', () => {
        panel.hidden ? openPanel() : closePanel();
    });

    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target)) closePanel();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closePanel();
    });

    label.textContent = select.value
        ? (select.querySelector(`option[value="${CSS.escape(select.value)}"]`)?.textContent || placeholder)
        : placeholder;
}

function syncCustomSelectLabel(selectId) {
    const select = document.getElementById(selectId);
    const label = document.getElementById(`${selectId}-trigger-label`);
    const panel = document.getElementById(`${selectId}-panel`);
    if (!select || !label) return;

    const selectedOption = select.value ? select.querySelector(`option[value="${CSS.escape(select.value)}"]`) : null;
    label.textContent = selectedOption ? selectedOption.textContent : 'Select a region...';

    if (panel) {
        panel.querySelectorAll('.custom-dropdown-option').forEach(item => {
            item.classList.toggle('selected', item.dataset.value === select.value);
        });
    }
}

async function loadOracleSshKeys(selectedKeyName) {
    const select = document.getElementById('oracle-ssh-key');
    if (!select) return;
    try {
        const response = await apiFetch('/settings/ssh-keys');
        if (!response.ok) return;
        const data = await response.json();
        if (!data.keys || data.keys.length === 0) {
            select.innerHTML = '<option value="">No keys detected under .ssh/</option>';
            return;
        }
        select.innerHTML = data.keys.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join('');
        if (selectedKeyName && data.keys.includes(selectedKeyName)) {
            select.value = selectedKeyName;
        }
    } catch (error) {
        console.error('Error loading SSH keys:', error);
    }
}

async function refreshOracleSshKeys() {
    const select = document.getElementById('oracle-ssh-key');
    const currentValue = select ? select.value : null;
    await loadOracleSshKeys(currentValue);
    showToast('SSH key list refreshed', 'success');
}

async function loadOracleApiKeyStatus() {
    const detectedBlock = document.getElementById('oracle-api-key-detected');
    const publicKeyDisplay = document.getElementById('oracle-api-public-key-display');
    if (!detectedBlock || !publicKeyDisplay) return;
    try {
        const response = await apiFetch('/settings/oracle-api-key');
        if (!response.ok) {
            detectedBlock.style.display = 'none';
            return;
        }
        const data = await response.json();
        detectedBlock.style.display = data.detected ? 'block' : 'none';
        publicKeyDisplay.value = data.public_key || '';
    } catch (error) {
        console.error('Error checking Oracle API key status:', error);
        detectedBlock.style.display = 'none';
    }
}

async function importOracleApiKey() {
    const btn = document.getElementById('oracle-api-key-import-btn');
    if (btn) btn.disabled = true;
    try {
        const response = await apiFetch('/settings/oracle-api-key/import', { method: 'POST' });
        const data = await response.json();
        if (response.ok) {
            // Only touch the fields this action actually changed server-side
            // (fingerprint + key-stored status) - a full loadSettings() here
            // would overwrite any other fields the operator has typed but
            // not saved yet (Tenancy OCID, Region, etc.) with whatever's
            // still in the DB, silently discarding unsaved input.
            setValueIfPresent('oracle-fingerprint', data.oracle_fingerprint);
            const apiKeyStatus = document.getElementById('oracle-api-key-status');
            if (apiKeyStatus) {
                apiKeyStatus.innerHTML = '<i class="fas fa-circle-check"></i> A key is stored.';
            }
            showToast('Oracle API key imported - fingerprint filled in. Click Save Settings to keep everything.', 'success');
        } else {
            showToast(data.detail || 'Failed to import key', 'error');
        }
    } catch (error) {
        console.error('Error importing Oracle API key:', error);
        showToast('Error importing Oracle API key', 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function toggleOracleApiKeyManualEntry() {
    const textarea = document.getElementById('oracle-api-key');
    const toggleBtn = document.getElementById('oracle-api-key-manual-toggle');
    if (!textarea || !toggleBtn) return;
    const showing = textarea.style.display !== 'none';
    textarea.style.display = showing ? 'none' : 'block';
    toggleBtn.textContent = showing ? 'Paste a key manually instead' : 'Cancel';
    if (showing) textarea.value = '';
}

function toggleOracleSettings() {
    const checkbox = document.getElementById('oracle-enabled');
    const fields = document.getElementById('oracle-settings-fields');
    if (checkbox && fields) {
        fields.style.display = checkbox.checked ? 'block' : 'none';
    }
}

async function saveSettings() {
    const payload = {
        timezone: getValue('timezone'),
        dns_servers: getValue('dns-servers'),
        encryption_level: parseInt(getValue('encryption-level'), 10) || undefined,
        kill_switch_enabled: getChecked('kill-switch'),
        log_level: getValue('log-level'),
        log_retention_days: parseInt(getValue('log-retention'), 10) || undefined,
        oracle_enabled: getChecked('oracle-enabled'),
        oracle_tenancy_ocid: getValue('oracle-tenancy-ocid'),
        oracle_user_ocid: getValue('oracle-user-ocid'),
        oracle_fingerprint: getValue('oracle-fingerprint'),
        oracle_region: getValue('oracle-region'),
        oracle_ssh_key_name: getValue('oracle-ssh-key'),
    };
    // Only send the API key if the operator actually typed a new one -
    // an empty field means "leave the stored key unchanged", not "clear it".
    const apiKeyValue = getValue('oracle-api-key');
    if (apiKeyValue) {
        payload.oracle_api_key = apiKeyValue;
    }

    try {
        const response = await apiFetch('/settings', {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Settings saved successfully', 'success');
            const apiKeyField = document.getElementById('oracle-api-key');
            if (apiKeyField) apiKeyField.value = '';
            loadSettings();
        } else {
            const data = await response.json();
            showToast(data.detail || 'Failed to save settings', 'error');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        showToast('Error saving settings', 'error');
    }
}

function resetSettings() {
    if (!confirm('Discard unsaved changes and reload the last saved settings?')) return;
    loadSettings();
}

function getValue(elementId) {
    const el = document.getElementById(elementId);
    return el ? el.value : null;
}

function getChecked(elementId) {
    const el = document.getElementById(elementId);
    return el ? el.checked : null;
}

// ========== USER MANAGEMENT FUNCTIONS ==========

// Show Add User Modal
function showAddUserModal() {
    const modal = document.getElementById('add-user-modal');
    if (modal) {
        modal.style.display = 'block';
        console.log('Add User modal shown');
    } else {
        console.error('Add User modal not found');
    }
}

// Close Add User Modal
function closeAddUserModal() {
    const modal = document.getElementById('add-user-modal');
    if (modal) {
        modal.style.display = 'none';
        // Reset form
        const form = document.getElementById('add-user-form');
        if (form) {
            form.reset();
        }
        console.log('Add User modal closed');
    }
}

// Handle Add User form submission
async function handleAddUser(event) {
    event.preventDefault();
    console.log('Adding new user');
    
    const formData = new FormData(event.target);
    
    // Get selected protocols
    const protocols = [];
    const protocolCheckboxes = document.querySelectorAll('input[name="user-protocols"]:checked');
    protocolCheckboxes.forEach(checkbox => {
        protocols.push(checkbox.value);
    });
    
    // Ensure at least one protocol is selected
    if (protocols.length === 0) {
        showToast('Please select at least one protocol', 'error');
        return;
    }
    
    const userData = {
        username: formData.get('user-username'),
        email: formData.get('user-email') || null,
        password: formData.get('user-password'),
        role: formData.get('user-role'),
        protocols: protocols
    };
    
    try {
        const response = await apiFetch('/users', {
            method: 'POST',
            body: JSON.stringify(userData)
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast('User created successfully', 'success');
            closeAddUserModal();
            // Reset form
            event.target.reset();
            // Reload users table
            loadUsers();
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to create user', 'error');
        }
    } catch (error) {
        console.error('Error creating user:', error);
        showToast('Error creating user', 'error');
    }
}

// Load and display users
async function loadUsers() {
    console.log('Loading users');
    try {
        const response = await apiFetch('/users');
        if (response.ok) {
            const data = await response.json();
            const users = Array.isArray(data) ? data : data.users || [];
            const tableBody = document.getElementById('users-table-body');
            if (tableBody) {
                if (users.length === 0) {
                    tableBody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center">No users found</td>
                        </tr>
                    `;
                } else {
                    tableBody.innerHTML = users.map(user => `
                        <tr>
                            <td>${user.username}</td>
                            <td>${user.email || '-'}</td>
                            <td><span class="role-badge role-${user.role}">${user.role}</span></td>
                            <td><span class="status-badge status-${user.is_active ? 'active' : 'inactive'}">${user.is_active ? 'Active' : 'Inactive'}</span></td>
                            <td>${new Date(user.created_at).toLocaleDateString()}</td>
                            <td>
                                <button class="btn btn-sm btn-secondary" onclick="console.log('Edit button clicked for user ${user.id}'); editUser(${user.id})">
                                    <i class="fas fa-edit"></i> Edit
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="console.log('Delete button clicked for user ${user.id}'); deleteUser(${user.id}, '${user.username}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `).join('');
                    console.log('User table updated with', users.length, 'users. Check if edit/delete buttons work now.');
                }
            }
        } else {
            console.error('Failed to load users');
            const tableBody = document.getElementById('users-table-body');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center text-danger">Failed to load users</td>
                    </tr>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

// Edit user functionality
async function editUser(userId) {
    console.log('Edit user called with userId:', userId);
    
    try {
        console.log('Fetching user data...');
        // First, fetch the user data
        const response = await apiFetch(`/api/users/${userId}`);
        
        if (!response.ok) {
            console.error('Failed to fetch user data, response status:', response.status);
            showToast('Failed to fetch user data', 'error');
            return;
        }
        
        const user = await response.json();
        console.log('User data received:', user);
        
        // Populate the edit form with user data
        document.getElementById('edit-user-id').value = user.id;
        document.getElementById('edit-user-username').value = user.username || '';
        document.getElementById('edit-user-email').value = user.email || '';
        document.getElementById('edit-user-password').value = ''; // Always empty for security
        document.getElementById('edit-user-role').value = user.role || 'user';
        document.getElementById('edit-user-status').value = user.status || 'active';
        
        // Handle protocols (assuming they're stored as an array or comma-separated string)
        const protocolCheckboxes = document.querySelectorAll('input[name="edit-user-protocols"]');
        protocolCheckboxes.forEach(checkbox => {
            checkbox.checked = false; // Reset all
        });
        
        if (user.protocols) {
            const userProtocols = Array.isArray(user.protocols) 
                ? user.protocols 
                : user.protocols.split(',');
            
            userProtocols.forEach(protocol => {
                const checkbox = document.querySelector(`input[name="edit-user-protocols"][value="${protocol.trim()}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                }
            });
        }
        
        console.log('Form populated, showing modal...');
        // Show the modal
        document.getElementById('edit-user-modal').style.display = 'flex';
        
    } catch (error) {
        console.error('Error fetching user data:', error);
        showToast('Failed to load user data for editing', 'error');
    }
}

// Close Edit User Modal
function closeEditUserModal() {
    document.getElementById('edit-user-modal').style.display = 'none';
    
    // Reset form
    const form = document.getElementById('edit-user-form');
    if (form) {
        form.reset();
    }
}

// Delete user functionality
async function deleteUser(userId, username) {
    if (!confirm(`Are you sure you want to delete user "${username}"?\n\nThis action cannot be undone and will remove all associated VPN configurations.`)) {
        return;
    }
    
    try {
        const response = await apiFetch(`/api/users/${userId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast(`User "${username}" deleted successfully`, 'success');
            loadUsers(); // Refresh the user list
        } else {
            const errorData = await response.json();
            showToast(errorData.detail || 'Failed to delete user', 'error');
        }
    } catch (error) {
        console.error('Error deleting user:', error);
        showToast('Failed to delete user', 'error');
    }
}

// ========== OPENVPN CLIENT MANAGEMENT FUNCTIONS ==========

// Show Add OpenVPN Client Modal
function showAddOpenVPNClientModal() {
    const modal = document.getElementById('add-openvpn-client-modal');
    if (modal) {
        modal.style.display = 'block';
        console.log('Add OpenVPN Client modal shown');
    } else {
        console.error('Add OpenVPN Client modal not found');
    }
}

// Close Add OpenVPN Client Modal
function closeAddOpenVPNClientModal() {
    const modal = document.getElementById('add-openvpn-client-modal');
    if (modal) {
        modal.style.display = 'none';
        // Reset form
        const form = document.getElementById('add-openvpn-client-form');
        if (form) {
            form.reset();
        }
        console.log('Add OpenVPN Client modal closed');
    }
}

// Handle Add OpenVPN Client form submission
async function handleAddOpenVPNClient(event) {
    event.preventDefault();
    console.log('Adding new OpenVPN client');
    
    const formData = new FormData(event.target);
    const clientData = {
        client_name: formData.get('openvpn-client-name'),
        user_id: 1, // TODO: Get current user ID from token
        protocol: formData.get('openvpn-client-protocol'),
        cipher: formData.get('openvpn-client-cipher'),
        dns_region: formData.get('openvpn-client-region') || 'default'
    };
    
    try {
        const response = await apiFetch('/vpn/openvpn/clients', {
            method: 'POST',
            body: JSON.stringify(clientData)
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast('OpenVPN client created successfully', 'success');
            closeAddOpenVPNClientModal();
            // Reset form
            event.target.reset();
            // Reload clients table
            loadOpenVPNClients();
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to create OpenVPN client', 'error');
        }
    } catch (error) {
        console.error('Error creating OpenVPN client:', error);
        showToast('Error creating OpenVPN client', 'error');
    }
}

// Load and display OpenVPN clients
async function loadOpenVPNClients() {
    console.log('Loading OpenVPN clients');
    try {
        const response = await apiFetch('/vpn/openvpn/clients');
        if (response.ok) {
            const data = await response.json();
            const clients = data.clients || [];
            const tableBody = document.getElementById('openvpn-clients-table');
            if (tableBody) {
                if (clients.length === 0) {
                    tableBody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center">No clients configured</td>
                        </tr>
                    `;
                } else {
                    tableBody.innerHTML = clients.map(client => {
                        const region = client.dns_region || 'default';
                        const regionLabel = region === 'default' ? '<span class="text-muted">Default</span>' : `<span class="status-badge status-active">${region.charAt(0).toUpperCase() + region.slice(1)}</span>`;
                        return `
                        <tr>
                            <td>${client.name}</td>
                            <td><span class="status-badge status-${client.status === 'active' ? 'active' : 'inactive'}">${client.status}</span></td>
                            <td>UDP</td>
                            <td>${regionLabel}</td>
                            <td>${new Date(client.created_at * 1000).toLocaleDateString()}</td>
                            <td>
                                <button class="btn btn-sm btn-secondary" onclick="downloadOpenVPNConfig('${client.name}')">
                                    <i class="fas fa-download"></i> Config
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="deleteOpenVPNClient('${client.name}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `;
                    }).join('');
                }
            }
        } else {
            console.error('Failed to load OpenVPN clients');
            const tableBody = document.getElementById('openvpn-clients-table');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center text-danger">Failed to load clients</td>
                    </tr>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading OpenVPN clients:', error);
    }
}

// Download OpenVPN client configuration file
async function downloadOpenVPNConfig(clientName) {
    try {
        const response = await apiFetch(`/vpn/openvpn/clients/${clientName}/config`);
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${clientName}.ovpn`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showToast('OpenVPN configuration downloaded successfully', 'success');
        } else {
            showToast('Failed to download OpenVPN configuration', 'error');
        }
    } catch (error) {
        console.error('Error downloading OpenVPN config:', error);
        showToast('Error downloading OpenVPN configuration', 'error');
    }
}

async function deleteOpenVPNClient(clientName) {
    if (!confirm(`Are you sure you want to delete OpenVPN client "${clientName}"?\n\nThis action cannot be undone and will remove the client configuration.`)) {
        return;
    }

    try {
        const response = await apiFetch(`/vpn/openvpn/clients/${clientName}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showToast(`Client "${clientName}" deleted successfully`, 'success');
            loadOpenVPNClients(); // Refresh the client list
        } else {
            const error = await response.json();
            showToast(`Failed to delete client: ${error.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error deleting OpenVPN client:', error);
        showToast('Failed to delete client. Check console for details.', 'error');
    }
}

// IKEv2 Functions

function showAddIKEv2UserModal() {
    const modal = document.getElementById('add-ikev2-user-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeAddIKEv2UserModal() {
    const modal = document.getElementById('add-ikev2-user-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    
    // Reset form
    const form = document.getElementById('add-ikev2-user-form');
    if (form) {
        form.reset();
    }
}

async function handleAddIKEv2User(event) {
    event.preventDefault();
    
    const username = document.getElementById('ikev2-username').value;
    const password = document.getElementById('ikev2-user-password').value;
    const confirmPassword = document.getElementById('ikev2-confirm-password').value;
    
    // Validate passwords match
    if (password !== confirmPassword) {
        showToast('Passwords do not match', 'error');
        return;
    }
    
    try {
        const response = await apiFetch('/api/ikev2/users', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
        
        if (response.ok) {
            showToast('IKEv2 user created successfully', 'success');
            closeAddIKEv2UserModal();
            loadIKEv2Users(); // Reload the users table
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to create user', 'error');
        }
    } catch (error) {
        console.error('Error creating IKEv2 user:', error);
        showToast('Failed to create user', 'error');
    }
}

async function loadIKEv2Users() {
    try {
        const response = await apiFetch('/api/ikev2/users');
        const users = await response.json();
        
        const tableBody = document.getElementById('ikev2-users-table');
        if (tableBody) {
            tableBody.innerHTML = users.map(user => `
                <tr>
                    <td>${user.username}</td>
                    <td><span class="status ${user.status}">${user.status}</span></td>
                    <td>${new Date(user.created).toLocaleDateString()}</td>
                    <td>${user.lastConnection ? new Date(user.lastConnection).toLocaleDateString() : 'Never'}</td>
                    <td>
                        <button class="btn btn-outline-danger btn-sm" onclick="deleteIKEv2User('${user.username}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        }
    } catch (error) {
        console.error('Error loading IKEv2 users:', error);
        showToast('Failed to load users', 'error');
    }
}

async function deleteIKEv2User(username) {
    if (!confirm(`Are you sure you want to delete IKEv2 user "${username}"?`)) {
        return;
    }
    
    try {
        const response = await apiFetch(`/api/ikev2/users/${username}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('IKEv2 user deleted successfully', 'success');
            loadIKEv2Users(); // Reload the users table
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to delete user', 'error');
        }
    } catch (error) {
        console.error('Error deleting IKEv2 user:', error);
        showToast('Failed to delete user', 'error');
    }
}

function copyText(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const textarea = document.createElement('textarea');
    textarea.value = element.textContent;
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
        document.execCommand('copy');
        showToast('Text copied to clipboard', 'success');
    } catch (err) {
        console.error('Failed to copy text: ', err);
        showToast('Failed to copy text', 'error');
    } finally {
        document.body.removeChild(textarea);
    }
}

// Configuration visibility toggle functions
function toggleConfigVisibility(elementId) {
    const element = document.getElementById(elementId);
    const toggleBtn = element.parentElement.querySelector('.toggle-visibility-btn i');
    
    if (!element || !toggleBtn) return;
    
    const isCurrentlyMasked = element.classList.contains('masked');
    const realValue = element.getAttribute('data-value');
    
    if (isCurrentlyMasked) {
        // Show real value
        element.textContent = realValue;
        element.classList.remove('masked');
        toggleBtn.className = 'fas fa-eye-slash';
        console.log(`Showing real value for ${elementId}`);
    } else {
        // Mask value
        const maskedValue = generateMaskedValue(realValue);
        element.textContent = maskedValue;
        element.classList.add('masked');
        toggleBtn.className = 'fas fa-eye';
        console.log(`Masking value for ${elementId}`);
    }
}

function copyConfigValue(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    // Always copy the real value, even if it's currently masked
    const realValue = element.getAttribute('data-value');
    
    const textarea = document.createElement('textarea');
    textarea.value = realValue;
    document.body.appendChild(textarea);
    
    try {
        textarea.select();
        document.execCommand('copy');
        showToast('Configuration value copied to clipboard', 'success');
        console.log(`Copied configuration value for ${elementId}`);
    } catch (err) {
        console.error('Failed to copy configuration value:', err);
        showToast('Failed to copy configuration value', 'error');
    } finally {
        document.body.removeChild(textarea);
    }
}

function generateMaskedValue(value) {
    if (!value) return '';
    
    const length = value.length;
    
    if (length <= 3) {
        // Very short values - mask completely
        return '•'.repeat(length);
    } else if (length <= 8) {
        // Short values - show first character
        return value.charAt(0) + '•'.repeat(length - 1);
    } else if (length <= 20) {
        // Medium values - show first few characters
        const visibleChars = Math.ceil(length * 0.2);
        return value.substring(0, visibleChars) + '•'.repeat(length - visibleChars);
    } else {
        // Long values - show first few characters and mask the rest
        const visibleChars = Math.min(8, Math.ceil(length * 0.15));
        return value.substring(0, visibleChars) + '•'.repeat(Math.min(40, length - visibleChars));
    }
}

// Mobile Navigation Functions
function toggleMobileMenu() {
    console.log('toggleMobileMenu called'); // Debug log
    const navMenu = document.getElementById('nav-menu');
    const toggleIcon = document.getElementById('nav-toggle-icon');
    
    console.log('navMenu:', navMenu); // Debug log
    console.log('toggleIcon:', toggleIcon); // Debug log
    
    if (navMenu && toggleIcon) {
        navMenu.classList.toggle('active');
        console.log('Menu classes after toggle:', navMenu.className); // Debug log
        
        // Change icon between hamburger and X
        if (navMenu.classList.contains('active')) {
            toggleIcon.className = 'fas fa-times';
            console.log('Menu opened - icon changed to X'); // Debug log
        } else {
            toggleIcon.className = 'fas fa-bars';
            console.log('Menu closed - icon changed to bars'); // Debug log
        }
    } else {
        console.error('navMenu or toggleIcon not found'); // Debug log
    }
}

// Close mobile menu when clicking nav items
function closeMobileMenu() {
    const navMenu = document.getElementById('nav-menu');
    const toggleIcon = document.getElementById('nav-toggle-icon');
    
    if (navMenu && navMenu.classList.contains('active')) {
        navMenu.classList.remove('active');
        if (toggleIcon) {
            toggleIcon.className = 'fas fa-bars';
        }
    }
}

// Close mobile menu when clicking outside
function handleOutsideClick(event) {
    const navbar = event.target.closest('.navbar');
    const navMenu = document.getElementById('nav-menu');
    
    if (!navbar && navMenu && navMenu.classList.contains('active')) {
        closeMobileMenu();
    }
}

// ========================================
// UNINSTALL FUNCTIONALITY
// ========================================

// WireGuard Uninstall Functions
function openRemovePeersModal() {
    document.getElementById('remove-all-peers-modal').style.display = 'block';
    document.getElementById('remove-peers-confirmation').value = '';
    document.getElementById('confirm-remove-peers-btn').disabled = true;
}

function openUninstallWireguardModal() {
    document.getElementById('uninstall-wireguard-modal').style.display = 'block';
    document.getElementById('uninstall-wireguard-confirmation').value = '';
    document.getElementById('confirm-uninstall-wireguard-btn').disabled = true;
}

function validateRemovePeersConfirmation() {
    const input = document.getElementById('remove-peers-confirmation');
    const btn = document.getElementById('confirm-remove-peers-btn');
    btn.disabled = input.value !== 'REMOVE ALL';
}

function validateUninstallWireguardConfirmation() {
    const input = document.getElementById('uninstall-wireguard-confirmation');
    const btn = document.getElementById('confirm-uninstall-wireguard-btn');
    btn.disabled = input.value !== 'UNINSTALL WIREGUARD';
}

async function removeAllWireguardPeers() {
    try {
        showToast('Removing all WireGuard peers...', 'warning');
        const response = await apiFetch('/vpn/wireguard/clients/all', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All WireGuard peers removed successfully', 'success');
            closeModal('remove-all-peers-modal');
            loadWireguardPeers();
        } else {
            showToast(`Error removing peers: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error removing WireGuard peers:', error);
        showToast('Failed to remove WireGuard peers', 'error');
    }
}

async function uninstallWireguard() {
    try {
        showToast('Uninstalling WireGuard service...', 'warning');
        const response = await apiFetch('/vpn/wireguard/uninstall', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('WireGuard service uninstalled successfully', 'success');
            closeModal('uninstall-wireguard-modal');
            loadWireguardPeers();
        } else {
            showToast(`Error uninstalling WireGuard: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error uninstalling WireGuard:', error);
        showToast('Failed to uninstall WireGuard service', 'error');
    }
}

// OpenVPN Uninstall Functions
function openRemoveOpenVPNClientsModal() {
    document.getElementById('remove-all-openvpn-clients-modal').style.display = 'block';
    document.getElementById('remove-openvpn-clients-confirmation').value = '';
    document.getElementById('confirm-remove-openvpn-clients-btn').disabled = true;
}

function openUninstallOpenVPNModal() {
    document.getElementById('uninstall-openvpn-modal').style.display = 'block';
    document.getElementById('uninstall-openvpn-confirmation').value = '';
    document.getElementById('confirm-uninstall-openvpn-btn').disabled = true;
}

function validateRemoveOpenVPNClientsConfirmation() {
    const input = document.getElementById('remove-openvpn-clients-confirmation');
    const btn = document.getElementById('confirm-remove-openvpn-clients-btn');
    btn.disabled = input.value !== 'REMOVE ALL';
}

function validateUninstallOpenVPNConfirmation() {
    const input = document.getElementById('uninstall-openvpn-confirmation');
    const btn = document.getElementById('confirm-uninstall-openvpn-btn');
    btn.disabled = input.value !== 'UNINSTALL OPENVPN';
}

async function removeAllOpenVPNClients() {
    try {
        showToast('Removing all OpenVPN clients...', 'warning');
        const response = await apiFetch('/vpn/openvpn/clients/all', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All OpenVPN clients removed successfully', 'success');
            closeModal('remove-all-openvpn-clients-modal');
            loadOpenVPNClients();
        } else {
            showToast(`Error removing clients: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error removing OpenVPN clients:', error);
        showToast('Failed to remove OpenVPN clients', 'error');
    }
}

async function uninstallOpenVPN() {
    try {
        showToast('Uninstalling OpenVPN service...', 'warning');
        const response = await apiFetch('/vpn/openvpn/uninstall', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('OpenVPN service uninstalled successfully', 'success');
            closeModal('uninstall-openvpn-modal');
            loadOpenVPNClients();
        } else {
            showToast(`Error uninstalling OpenVPN: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error uninstalling OpenVPN:', error);
        showToast('Failed to uninstall OpenVPN service', 'error');
    }
}

// IKEv2 Uninstall Functions
function openRemoveIKEv2ClientsModal() {
    document.getElementById('remove-all-ikev2-clients-modal').style.display = 'block';
    document.getElementById('remove-ikev2-clients-confirmation').value = '';
    document.getElementById('confirm-remove-ikev2-clients-btn').disabled = true;
}

function openUninstallIKEv2Modal() {
    document.getElementById('uninstall-ikev2-modal').style.display = 'block';
    document.getElementById('uninstall-ikev2-confirmation').value = '';
    document.getElementById('confirm-uninstall-ikev2-btn').disabled = true;
}

function validateRemoveIKEv2ClientsConfirmation() {
    const input = document.getElementById('remove-ikev2-clients-confirmation');
    const btn = document.getElementById('confirm-remove-ikev2-clients-btn');
    btn.disabled = input.value !== 'REMOVE ALL';
}

function validateUninstallIKEv2Confirmation() {
    const input = document.getElementById('uninstall-ikev2-confirmation');
    const btn = document.getElementById('confirm-uninstall-ikev2-btn');
    btn.disabled = input.value !== 'UNINSTALL IKEV2';
}

async function removeAllIKEv2Clients() {
    try {
        showToast('Removing all IKEv2 clients...', 'warning');
        const response = await apiFetch('/vpn/ikev2/clients/all', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All IKEv2 clients removed successfully', 'success');
            closeModal('remove-all-ikev2-clients-modal');
            loadIKEv2Users();
        } else {
            showToast(`Error removing clients: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error removing IKEv2 clients:', error);
        showToast('Failed to remove IKEv2 clients', 'error');
    }
}

async function uninstallIKEv2() {
    try {
        showToast('Uninstalling IKEv2 service...', 'warning');
        const response = await apiFetch('/vpn/ikev2/uninstall', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('IKEv2 service uninstalled successfully', 'success');
            closeModal('uninstall-ikev2-modal');
            loadIKEv2Users();
        } else {
            showToast(`Error uninstalling IKEv2: ${data.detail}`, 'error');
        }
    } catch (error) {
        console.error('Error uninstalling IKEv2:', error);
        showToast('Failed to uninstall IKEv2 service', 'error');
    }
}

// Helper function to close modals
function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// Refresh tab functions  
function refreshWireguardTab() {
    if (document.getElementById('wireguard').style.display === 'block') {
        loadWireguardPeers();
    }
}

function refreshOpenVpnTab() {
    if (document.getElementById('openvpn').style.display === 'block') {
        loadOpenVPNClients();
    }
}

function refreshIkev2Tab() {
    if (document.getElementById('ikev2').style.display === 'block') {
        loadIKEv2Users();
    }
}

// Export functions for global access
window.switchTab = switchTab;
window.handleLogout = handleLogout;
window.showAddPeerModal = showAddPeerModal;
window.closeAddPeerModal = closeAddPeerModal;
window.editPeer = editPeer;
window.closeEditPeerModal = closeEditPeerModal;
window.downloadPeerConfig = downloadPeerConfig;
window.deletePeer = deletePeer;
window.showAddRegionModal = showAddRegionModal;
window.closeAddRegionModal = closeAddRegionModal;
window.showAddOracleRegionModal = showAddOracleRegionModal;
window.closeAddOracleRegionModal = closeAddOracleRegionModal;
window.testRegionHealth = testRegionHealth;
window.deleteRegion = deleteRegion;
window.showAddUserModal = showAddUserModal;
window.closeAddUserModal = closeAddUserModal;
window.editUser = editUser;
window.deleteUser = deleteUser;
window.showAddOpenVPNClientModal = showAddOpenVPNClientModal;
window.closeAddOpenVPNClientModal = closeAddOpenVPNClientModal;
window.downloadOpenVPNConfig = downloadOpenVPNConfig;
window.deleteOpenVPNClient = deleteOpenVPNClient;
window.showAddIKEv2UserModal = showAddIKEv2UserModal;
window.closeAddIKEv2UserModal = closeAddIKEv2UserModal;
window.copyText = copyText;
window.toggleConfigVisibility = toggleConfigVisibility;
window.copyConfigValue = copyConfigValue;
window.toggleMobileMenu = toggleMobileMenu;
window.closeMobileMenu = closeMobileMenu;

// Uninstall function exports
window.openRemovePeersModal = openRemovePeersModal;
window.openUninstallWireguardModal = openUninstallWireguardModal;
window.validateRemovePeersConfirmation = validateRemovePeersConfirmation;
window.validateUninstallWireguardConfirmation = validateUninstallWireguardConfirmation;
window.removeAllWireguardPeers = removeAllWireguardPeers;
window.uninstallWireguard = uninstallWireguard;
window.openRemoveOpenVPNClientsModal = openRemoveOpenVPNClientsModal;
window.openUninstallOpenVPNModal = openUninstallOpenVPNModal;
window.validateRemoveOpenVPNClientsConfirmation = validateRemoveOpenVPNClientsConfirmation;
window.validateUninstallOpenVPNConfirmation = validateUninstallOpenVPNConfirmation;
window.removeAllOpenVPNClients = removeAllOpenVPNClients;
window.uninstallOpenVPN = uninstallOpenVPN;
window.openRemoveIKEv2ClientsModal = openRemoveIKEv2ClientsModal;
window.openUninstallIKEv2Modal = openUninstallIKEv2Modal;
window.validateRemoveIKEv2ClientsConfirmation = validateRemoveIKEv2ClientsConfirmation;
window.validateUninstallIKEv2Confirmation = validateUninstallIKEv2Confirmation;
window.removeAllIKEv2Clients = removeAllIKEv2Clients;
window.uninstallIKEv2 = uninstallIKEv2;
window.closeModal = closeModal;
window.saveSettings = saveSettings;
window.resetSettings = resetSettings;
window.toggleOracleSettings = toggleOracleSettings;
window.refreshOracleSshKeys = refreshOracleSshKeys;
window.importOracleApiKey = importOracleApiKey;
window.toggleOracleApiKeyManualEntry = toggleOracleApiKeyManualEntry;
