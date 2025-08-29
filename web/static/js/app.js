// BartoloVPN Main JavaScript Application

// Global variables
let currentUser = null;
let isLoggedIn = false;

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
    const loginButton = document.getElementById('login-button');
    const originalText = loginButton.textContent;
    loginButton.textContent = 'Logging in...';
    loginButton.disabled = true;
    loginError.textContent = '';
    
    try {
        const response = await fetch('/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password }),
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Show success message
            loginError.style.color = 'green';
            loginError.textContent = 'Login successful! Redirecting...';
            
            // Store token
            localStorage.setItem('authToken', data.access_token);
            currentUser = { username: data.username };
            isLoggedIn = true;
            
            // Redirect to dashboard after a short delay
            setTimeout(() => {
                window.location.href = '/dashboard';
            }, 1000);
        } else {
            loginError.style.color = 'red';
            loginError.textContent = data.detail || 'Login failed';
        }
    } catch (error) {
        console.error('Login error:', error);
        loginError.style.color = 'red';
        loginError.textContent = 'Network error. Please try again.';
    } finally {
        // Reset button state
        loginButton.textContent = originalText;
        loginButton.disabled = false;
    }
}

// Logout functionality
async function handleLogout() {
    try {
        const response = await fetch('/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });
        
        if (response.ok) {
            // Clear local storage
            localStorage.removeItem('authToken');
            currentUser = null;
            isLoggedIn = false;
            
            // Redirect to login
            window.location.href = '/login';
        }
    } catch (error) {
        console.error('Logout error:', error);
        // Still redirect to login even if logout fails
        localStorage.removeItem('authToken');
        window.location.href = '/login';
    }
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
        const response = await fetch('/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, email, password }),
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Show success message
            registerError.style.color = 'green';
            registerError.textContent = 'Registration successful! Please login.';
            
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
    currentUser = null;
    isLoggedIn = false;
    window.location.href = '/login';
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
        const statusResponse = await fetch('/status', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
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
    if (data.network) {
        const bandwidthUsage = document.getElementById('bandwidth-usage');
        if (bandwidthUsage) {
            bandwidthUsage.textContent = data.network.bandwidth_used || '0 MB/s';
        }
    }
    
    // Update active users (sum of all connections)
    const activeUsers = document.getElementById('active-users');
    if (activeUsers && data.vpn) {
        const totalConnections = (data.vpn.wireguard?.connections || 0) + 
                                (data.vpn.openvpn?.connections || 0) + 
                                (data.vpn.ikev2?.connections || 0);
        activeUsers.textContent = totalConnections;
    }
    
    // Load system resources
    loadSystemResources();
}

// Load system resources (CPU, Memory, Disk)
async function loadSystemResources() {
    try {
        const token = localStorage.getItem('authToken');
        if (!token) return;
        
        const response = await fetch('/api/system/resources', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
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

// Logout functionality
function handleLogout() {
    showLogin();
}

// Tab switching functionality
function switchTab(tabName) {
    // Hide all tab content
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => {
        content.style.display = 'none';
    });
    
    // Remove active class from all nav items
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`${tabName}-tab`);
    if (selectedTab) {
        selectedTab.style.display = 'block';
    }
    
    // Add active class to selected nav item
    const selectedNavItem = document.querySelector(`[data-tab="${tabName}"]`);
    if (selectedNavItem) {
        selectedNavItem.classList.add('active');
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
        console.log('Token found, loading dashboard...');
        // Validate token and show dashboard
        loadDashboardData();
    } else {
        console.log('No token found, showing login screen...');
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
});

// Export functions for global access
window.switchTab = switchTab;
window.handleLogout = handleLogout;
