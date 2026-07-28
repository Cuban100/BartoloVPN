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
    
    // Update VPN service statuses
    if (data.vpn) {
        // WireGuard status
        const wireguardStatus = document.getElementById('wireguard-status');
        if (wireguardStatus && data.vpn.wireguard) {
            wireguardStatus.textContent = data.vpn.wireguard.status || 'Unknown';
            wireguardStatus.className = `stat-value ${data.vpn.wireguard.status === 'running' ? 'status-healthy' : 'status-warning'}`;
        }
        
        // OpenVPN status
        const openvpnStatus = document.getElementById('openvpn-status');
        if (openvpnStatus && data.vpn.openvpn) {
            openvpnStatus.textContent = data.vpn.openvpn.status || 'Unknown';
            openvpnStatus.className = `stat-value ${data.vpn.openvpn.status === 'running' ? 'status-healthy' : 'status-warning'}`;
        }
        
        // IKEv2 status
        const ikev2Status = document.getElementById('ikev2-status');
        if (ikev2Status && data.vpn.ikev2) {
            ikev2Status.textContent = data.vpn.ikev2.status || 'Unknown';
            ikev2Status.className = `stat-value ${data.vpn.ikev2.status === 'running' ? 'status-healthy' : 'status-warning'}`;
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
    // Update CPU
    const cpuUsage = data.cpu?.usage || data.cpu_percent || 0;
    const cpuLoad = data.cpu?.load_average || 0;
    
    const cpuUsageEl = document.getElementById('cpu-usage');
    const cpuProgressEl = document.getElementById('cpu-progress');
    const cpuLoadEl = document.getElementById('cpu-load');
    
    if (cpuUsageEl) cpuUsageEl.textContent = `${cpuUsage.toFixed(1)}%`;
    if (cpuProgressEl) cpuProgressEl.style.width = `${cpuUsage}%`;
    if (cpuLoadEl) cpuLoadEl.textContent = cpuLoad.toFixed(2);
    
    // Update Memory
    const memoryUsage = data.memory?.percent || data.memory_percent || 0;
    const memoryUsed = data.memory?.used_gb || 0;
    const memoryTotal = data.memory?.total_gb || 0;
    
    const memoryUsageEl = document.getElementById('memory-usage');
    const memoryProgressEl = document.getElementById('memory-progress');
    const memoryUsedEl = document.getElementById('memory-used');
    const memoryTotalEl = document.getElementById('memory-total');
    
    if (memoryUsageEl) memoryUsageEl.textContent = `${memoryUsage.toFixed(1)}%`;
    if (memoryProgressEl) memoryProgressEl.style.width = `${memoryUsage}%`;
    if (memoryUsedEl) memoryUsedEl.textContent = `${memoryUsed.toFixed(1)} GB`;
    if (memoryTotalEl) memoryTotalEl.textContent = `${memoryTotal.toFixed(1)} GB`;
    
    // Update Disk
    const diskUsage = data.disk?.percent || data.disk_percent || 0;
    const diskUsed = data.disk?.used_gb || 0;
    const diskTotal = data.disk?.total_gb || 0;
    
    const diskUsageEl = document.getElementById('disk-usage');
    const diskProgressEl = document.getElementById('disk-progress');
    const diskUsedEl = document.getElementById('disk-used');
    const diskTotalEl = document.getElementById('disk-total');
    
    if (diskUsageEl) diskUsageEl.textContent = `${diskUsage.toFixed(1)}%`;
    if (diskProgressEl) diskProgressEl.style.width = `${diskUsage}%`;
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
    const ikev2ConnectionsEl = document.getElementById('ikev2-connections');
    const ikev2BandwidthEl = document.getElementById('ikev2-bandwidth');
    const ikev2LatencyEl = document.getElementById('ikev2-latency');
    const ikev2TransferEl = document.getElementById('ikev2-transfer');
    
    if (ikev2ConnectionsEl) ikev2ConnectionsEl.textContent = ikev2Data.connections || 0;
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
            statusDot.className = 'status-indicator active';
            statusText.textContent = 'Active';
        } else {
            statusDot.className = 'status-indicator inactive';
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
    } else if (tabName === 'users') {
        loadUsers();
    } else if (tabName === 'openvpn') {
        loadOpenVPNClients();
    } else if (tabName === 'monitoring') {
        initializeMonitoring();
    } else if (tabName === 'activity') {
        loadDnsActivity();
    } else {
        // Stop monitoring when switching away from monitoring tab
        cleanupMonitoring();
    }
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing elements...');
    
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
    } else {
        console.error('Add peer modal not found');
    }
}

function closeAddPeerModal() {
    console.log('Closing Add Peer modal');
    const modal = document.getElementById('add-peer-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Edit peer functionality
async function editPeer(peerName) {
    console.log('Edit peer called with peerName:', peerName);
    
    try {
        console.log('Fetching peer data...');
        // For now, we'll populate with the peer name and default values
        // In a real implementation, you'd fetch the current peer configuration
        
        // Populate the edit form with peer data
        document.getElementById('edit-peer-current-name').value = peerName;
        document.getElementById('edit-peer-name').value = peerName;
        document.getElementById('edit-peer-allowed-ips').value = '0.0.0.0/0';
        
        // Show the edit modal
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
        allowed_ips: formData.get('peer-allowed-ips') || "0.0.0.0/0"
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
    if (!modal || !img) {
        console.error('QR modal not found');
        return;
    }
    img.src = `data:image/png;base64,${qrCodeBase64}`;
    if (nameEl) nameEl.textContent = peerName || '';
    modal.style.display = 'flex';
}

function closePeerQrModal() {
    const modal = document.getElementById('peer-qr-modal');
    if (modal) modal.style.display = 'none';
}

// Fetch and show the QR code for an already-existing peer
async function showPeerQr(peerName) {
    try {
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}/qrcode`);
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
    
    // For now, since we don't have a PUT endpoint, we'll show a message
    // In a real implementation, you would call a PUT endpoint
    try {
        // TODO: Implement PUT /vpn/wireguard/peers/{peer_name} endpoint
        showToast('Edit functionality will be implemented with API endpoint', 'info');
        console.log('Edit peer data:', { currentName, newName, allowedIPs });
        
        closeEditPeerModal();
        // In a real implementation, you would reload the peers table
        // loadWireguardPeers();
        
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
                            <td colspan="5" class="text-center">No peers configured</td>
                        </tr>
                    `;
                } else {
                    tableBody.innerHTML = peers.map(peer => `
                        <tr>
                            <td>${peer.name}</td>
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
                                <button class="btn btn-sm btn-secondary" onclick="console.log('Edit peer clicked for ${peer.name}'); editPeer('${peer.name}')">
                                    <i class="fas fa-edit"></i> Edit
                                </button>
                                <button class="btn btn-sm btn-secondary" onclick="downloadPeerConfig('${peer.name}')">
                                    <i class="fas fa-download"></i> Config
                                </button>
                                <button class="btn btn-sm btn-secondary" onclick="showPeerQr('${peer.name}')">
                                    <i class="fas fa-qrcode"></i> QR
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="console.log('Delete peer clicked for ${peer.name}'); deletePeer('${peer.name}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `).join('');
                    console.log('WireGuard peer table updated with', peers.length, 'peers. Check if edit/delete buttons work now.');
                }
            }
        } else {
            console.error('Failed to load peers');
            const tableBody = document.getElementById('wireguard-peers-table');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="5" class="text-center text-danger">Failed to load peers</td>
                    </tr>
                `;
            }
        }
    } catch (error) {
        console.error('Error loading peers:', error);
    }
}

// Load and render the DNS/domain Activity tab
async function loadDnsActivity() {
    console.log('Loading DNS activity');
    const tableBody = document.getElementById('dns-activity-table');
    const peerFilter = document.getElementById('activity-peer-filter');
    const selectedPeerIp = peerFilter ? peerFilter.value : '';

    try {
        const url = selectedPeerIp
            ? `/api/dns/queries?peer_ip=${encodeURIComponent(selectedPeerIp)}`
            : '/api/dns/queries';
        const response = await apiFetch(url);
        if (!response.ok) {
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">Failed to load activity</td></tr>';
            }
            return;
        }
        const data = await response.json();
        const queries = data.queries || [];

        // Populate the peer filter dropdown with peers seen in the results,
        // without wiping out the user's current selection
        if (peerFilter) {
            const seen = new Map();
            queries.forEach(q => seen.set(q.peer_ip, q.peer_name));
            const currentValue = peerFilter.value;
            peerFilter.innerHTML = '<option value="">All peers</option>' +
                Array.from(seen.entries()).map(([ip, name]) =>
                    `<option value="${escapeHtml(ip)}">${escapeHtml(name)}</option>`
                ).join('');
            peerFilter.value = currentValue;
        }

        if (!tableBody) return;

        if (queries.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="3" class="text-center">No DNS activity recorded yet</td></tr>';
            return;
        }

        tableBody.innerHTML = queries.map(q => `
            <tr>
                <td>${escapeHtml(new Date(q.timestamp + 'Z').toLocaleString())}</td>
                <td>${escapeHtml(q.peer_name)}</td>
                <td>${escapeHtml(q.domain)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading DNS activity:', error);
        if (tableBody) {
            tableBody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">Error loading activity</td></tr>';
        }
    }
}

// Download peer configuration file
async function downloadPeerConfig(peerName) {
    try {
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}/config`);
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

// Delete peer (placeholder - needs DELETE endpoint)
async function deletePeer(peerName) {
    if (!confirm(`Are you sure you want to delete peer "${peerName}"?\n\nThis action cannot be undone and will remove the peer configuration.`)) {
        return;
    }
    
    try {
        console.log('Deleting peer:', peerName);
        const response = await apiFetch(`/vpn/wireguard/peers/${peerName}`, {
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
        cipher: formData.get('openvpn-client-cipher')
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
                            <td colspan="5" class="text-center">No clients configured</td>
                        </tr>
                    `;
                } else {
                    tableBody.innerHTML = clients.map(client => `
                        <tr>
                            <td>${client.name}</td>
                            <td><span class="status-badge status-${client.status === 'active' ? 'active' : 'inactive'}">${client.status}</span></td>
                            <td>UDP</td>
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
                    `).join('');
                }
            }
        } else {
            console.error('Failed to load OpenVPN clients');
            const tableBody = document.getElementById('openvpn-clients-table');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="5" class="text-center text-danger">Failed to load clients</td>
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

// Delete OpenVPN client (placeholder - needs DELETE endpoint)
async function deleteOpenVPNClient(clientName) {
    if (confirm(`Are you sure you want to delete OpenVPN client "${clientName}"?`)) {
        showToast('Delete OpenVPN client functionality not yet implemented', 'info');
        // TODO: Implement DELETE /vpn/openvpn/clients/{client_name} endpoint
    }
}

// WireGuard Instructions Functions
function toggleInstructions() {
    const container = document.getElementById('wireguard-instructions');
    const toggleBtn = document.getElementById('instructions-toggle');
    
    if (container.style.display === 'none') {
        container.style.display = 'block';
        container.classList.add('expanded');
        toggleBtn.textContent = 'Hide Instructions';
        // Add smooth expand animation
        container.style.maxHeight = '0px';
        setTimeout(() => {
            container.style.maxHeight = '2000px';
        }, 10);
    } else {
        container.style.maxHeight = '0px';
        toggleBtn.textContent = 'Show Instructions';
        setTimeout(() => {
            container.style.display = 'none';
            container.classList.remove('expanded');
        }, 300);
    }
}

function showInstructionTab(tabName) {
    // Hide all tabs
    const tabs = document.querySelectorAll('.instruction-tab');
    tabs.forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all tab buttons
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`${tabName}-tab`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    // Add active class to clicked button
    const clickedButton = event.target;
    clickedButton.classList.add('active');
}

function copyToClipboard(button) {
    const codeBlock = button.previousElementSibling;
    const text = codeBlock.textContent;
    
    // Create temporary textarea to copy text
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
        document.execCommand('copy');
        
        // Visual feedback
        const originalText = button.textContent;
        button.textContent = 'Copied!';
        button.classList.add('copied');
        
        setTimeout(() => {
            button.textContent = originalText;
            button.classList.remove('copied');
        }, 2000);
        
        showToast('Code copied to clipboard', 'success');
    } catch (err) {
        console.error('Failed to copy text: ', err);
        showToast('Failed to copy code', 'error');
    } finally {
        document.body.removeChild(textarea);
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

function toggleIKEv2Instructions() {
    const instructionsDiv = document.getElementById('ikev2-instructions');
    const toggleButton = document.getElementById('ikev2-instructions-toggle');
    
    if (instructionsDiv.style.display === 'none') {
        instructionsDiv.style.display = 'block';
        toggleButton.textContent = 'Hide Instructions';
    } else {
        instructionsDiv.style.display = 'none';
        toggleButton.textContent = 'Show Instructions';
    }
}

function showIKEv2OSInstructions(osType) {
    // Hide all OS instruction divs
    const allInstructions = document.querySelectorAll('#ikev2-instructions .os-instructions');
    allInstructions.forEach(div => {
        div.style.display = 'none';
    });
    
    // Remove active class from all OS buttons
    const allButtons = document.querySelectorAll('#ikev2-instructions .os-btn');
    allButtons.forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected OS instructions
    const targetDiv = document.getElementById(`ikev2-${osType}-instructions`);
    if (targetDiv) {
        targetDiv.style.display = 'block';
    }
    
    // Add active class to selected button
    const targetButton = document.getElementById(`ikev2-os-${osType}`);
    if (targetButton) {
        targetButton.classList.add('active');
    }
    
    // Update server IP in all instruction sections for the selected OS
    updateIKEv2ServerIP();
}

function showIKEv2LinuxDistro(distro) {
    // Hide all distro install sections
    const allDistros = document.querySelectorAll('#ikev2-linux-instructions .distro-install');
    allDistros.forEach(div => {
        div.classList.remove('active');
        div.style.display = 'none';
    });
    
    // Remove active class from all tab buttons
    const allTabs = document.querySelectorAll('#ikev2-linux-instructions .tab-button');
    allTabs.forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected distro
    const targetDiv = document.getElementById(`ikev2-${distro}-install`);
    if (targetDiv) {
        targetDiv.classList.add('active');
        targetDiv.style.display = 'block';
    }
    
    // Add active class to clicked button
    event.target.classList.add('active');
}

function updateIKEv2ServerIP() {
    // Get server IP (you would implement this based on your backend)
    // For now, we'll use a placeholder
    const serverIP = window.location.hostname; // or fetch from API
    
    // Update all server IP elements in IKEv2 instructions
    const serverIPElements = document.querySelectorAll('[id*="server-ip"], [id*="remote-id"]');
    serverIPElements.forEach(element => {
        if (element.id.includes('ikev2') || element.closest('#ikev2-instructions')) {
            element.textContent = serverIP;
        }
    });
}

function copyServerIP() {
    const serverIP = window.location.hostname;
    
    const textarea = document.createElement('textarea');
    textarea.value = serverIP;
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
        document.execCommand('copy');
        showToast('Server IP copied to clipboard', 'success');
    } catch (err) {
        console.error('Failed to copy server IP: ', err);
        showToast('Failed to copy server IP', 'error');
    } finally {
        document.body.removeChild(textarea);
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
    document.getElementById('remove-peers-modal').style.display = 'block';
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
        const response = await apiFetch('/api/vpn/wireguard/clients', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All WireGuard peers removed successfully', 'success');
            closeModal('remove-peers-modal');
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
        const response = await apiFetch('/api/vpn/wireguard/uninstall', {
            method: 'DELETE',
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
    document.getElementById('remove-openvpn-clients-modal').style.display = 'block';
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
        const response = await apiFetch('/api/vpn/openvpn/clients', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All OpenVPN clients removed successfully', 'success');
            closeModal('remove-openvpn-clients-modal');
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
        const response = await apiFetch('/api/vpn/openvpn/uninstall', {
            method: 'DELETE',
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
    document.getElementById('remove-ikev2-clients-modal').style.display = 'block';
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
        const response = await apiFetch('/api/vpn/ikev2/clients', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        const data = await response.json();
        if (response.ok) {
            showToast('All IKEv2 clients removed successfully', 'success');
            closeModal('remove-ikev2-clients-modal');
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
        const response = await apiFetch('/api/vpn/ikev2/uninstall', {
            method: 'DELETE',
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
window.showAddUserModal = showAddUserModal;
window.closeAddUserModal = closeAddUserModal;
window.editUser = editUser;
window.deleteUser = deleteUser;
window.showAddOpenVPNClientModal = showAddOpenVPNClientModal;
window.closeAddOpenVPNClientModal = closeAddOpenVPNClientModal;
window.downloadOpenVPNConfig = downloadOpenVPNConfig;
window.deleteOpenVPNClient = deleteOpenVPNClient;
window.toggleInstructions = toggleInstructions;
window.showInstructionTab = showInstructionTab;
window.copyToClipboard = copyToClipboard;
window.showAddIKEv2UserModal = showAddIKEv2UserModal;
window.closeAddIKEv2UserModal = closeAddIKEv2UserModal;
window.toggleIKEv2Instructions = toggleIKEv2Instructions;
window.showIKEv2OSInstructions = showIKEv2OSInstructions;
window.showIKEv2LinuxDistro = showIKEv2LinuxDistro;
window.copyServerIP = copyServerIP;
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
