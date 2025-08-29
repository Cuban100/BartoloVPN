// BartoloVPN Main JavaScript Application

// Global variables
let currentUser = null;
let isLoggedIn = false;
let toastsContainer = null;

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

// Load system resources (CPU, Memory, Disk)
async function loadSystemResources() {
    try {
        const token = localStorage.getItem('authToken');
        if (!token) return;
        
    const response = await apiFetch('/api/system/resources');
        
        if (response.ok) {
            const data = await response.json();
            updateSystemResources(data);
        }
    } catch (error) {
        console.error('Error loading system resources:', error);
    }
}

// Update system resources display
function updateSystemResources(data) {
    // CPU Usage
    const cpuProgress = document.getElementById('cpu-progress');
    const cpuPercent = document.getElementById('cpu-percent');
    if (cpuProgress && cpuPercent) {
        const cpuValue = data.cpu_percent || 0;
        cpuProgress.style.width = `${cpuValue}%`;
        cpuPercent.textContent = `${cpuValue}%`;
    }
    
    // Memory Usage
    const memoryProgress = document.getElementById('memory-progress');
    const memoryPercent = document.getElementById('memory-percent');
    if (memoryProgress && memoryPercent) {
        const memoryValue = data.memory_percent || 0;
        memoryProgress.style.width = `${memoryValue}%`;
        memoryPercent.textContent = `${memoryValue}%`;
    }
    
    // Disk Usage
    const diskProgress = document.getElementById('disk-progress');
    const diskPercent = document.getElementById('disk-percent');
    if (diskProgress && diskPercent) {
        const diskValue = data.disk_percent || 0;
        diskProgress.style.width = `${diskValue}%`;
        diskPercent.textContent = `${diskValue}%`;
    }
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
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to add peer', 'error');
        }
    } catch (error) {
        console.error('Error adding peer:', error);
        showToast('Error adding peer', 'error');
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
                            <td>***...${peer.name.slice(-4)}</td>
                            <td>${peer.ip}</td>
                            <td><span class="status-badge status-active">Active</span></td>
                            <td>
                                <button class="btn btn-sm btn-secondary" onclick="downloadPeerConfig('${peer.name}')">
                                    <i class="fas fa-download"></i> Config
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="deletePeer('${peer.name}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `).join('');
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
    if (confirm(`Are you sure you want to delete peer "${peerName}"?`)) {
        showToast('Delete functionality not yet implemented', 'info');
        // TODO: Implement DELETE /vpn/wireguard/peers/{peer_name} endpoint
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
                                <button class="btn btn-sm btn-secondary" onclick="editUser(${user.id})">
                                    <i class="fas fa-edit"></i> Edit
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="deleteUser(${user.id}, '${user.username}')">
                                    <i class="fas fa-trash"></i> Delete
                                </button>
                            </td>
                        </tr>
                    `).join('');
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

// Edit user (placeholder)
function editUser(userId) {
    showToast('Edit user functionality not yet implemented', 'info');
    // TODO: Implement edit user modal and functionality
}

// Delete user (placeholder)
function deleteUser(userId, username) {
    if (confirm(`Are you sure you want to delete user "${username}"?`)) {
        showToast('Delete user functionality not yet implemented', 'info');
        // TODO: Implement DELETE /users/{user_id} endpoint
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

// Export functions for global access
window.switchTab = switchTab;
window.handleLogout = handleLogout;
window.showAddPeerModal = showAddPeerModal;
window.closeAddPeerModal = closeAddPeerModal;
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
