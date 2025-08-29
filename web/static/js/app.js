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
            // Store token
            localStorage.setItem('authToken', data.access_token);
            currentUser = { username: data.username };
            isLoggedIn = true;
            
            console.log('Login successful, showing dashboard...');
            // Show dashboard
            showDashboard();
        } else {
            loginError.textContent = data.detail || 'Login failed';
        }
    } catch (error) {
        console.error('Login error:', error);
        loginError.textContent = 'Network error. Please try again.';
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
            // Registration successful, switch to login
            registerError.textContent = '';
            toggleLoginRegister();
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
        console.log('Login screen hidden');
    }
    
    if (dashboard) {
        dashboard.style.display = 'block';
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
    dashboard.style.display = 'none';
    loginScreen.style.display = 'block';
    localStorage.removeItem('authToken');
    currentUser = null;
    isLoggedIn = false;
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
    // Update status indicators
    const systemStatus = document.getElementById('system-status');
    if (systemStatus) {
        systemStatus.textContent = data.status || 'Unknown';
        systemStatus.className = `stat-value ${data.status === 'healthy' ? 'status-healthy' : 'status-warning'}`;
    }
    
    // Update other status elements...
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
