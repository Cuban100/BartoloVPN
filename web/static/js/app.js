// BartoloVPN Main JavaScript Application

// Global variables
let currentUser = null;
let isLoggedIn = false;

// DOM elements
const loginScreen = document.getElementById('login-screen');
const dashboard = document.getElementById('dashboard');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const toggleForm = document.getElementById('toggle-form');
const toggleText = document.getElementById('toggle-text');
const toggleButtonText = document.getElementById('toggle-button-text');
const loginError = document.getElementById('login-error');
const registerError = document.getElementById('register-error');

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
            currentUser = data.user;
            isLoggedIn = true;
            
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
    loginScreen.style.display = 'none';
    dashboard.style.display = 'block';
    
    // Update user info
    if (currentUser) {
        document.getElementById('current-user').textContent = currentUser.username;
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
    // Check if user is already logged in
    const token = localStorage.getItem('authToken');
    if (token) {
        // Validate token and show dashboard
        loadDashboardData();
    }
    
    // Form event listeners
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }
    
    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
    }
    
    if (toggleForm) {
        toggleForm.addEventListener('click', toggleLoginRegister);
    }
    
    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }
    
    // Tab navigation
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
});

// Export functions for global access
window.switchTab = switchTab;
window.handleLogout = handleLogout;
