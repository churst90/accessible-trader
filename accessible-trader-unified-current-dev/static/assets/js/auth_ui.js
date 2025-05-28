// static/assets/js/auth_ui.js

import { loginUser, logoutUser, getToken, registerUser } from './modules/dataService.js'; // Added registerUser

function updateAuthUI() {
    const token = getToken();
    const isLoggedIn = !!token;

    const profileLink = document.getElementById('profile-link');
    const credentialsLink = document.getElementById('credentials-link');
    const botsLink = document.getElementById('bots-link');
    const logoutLink = document.getElementById('logout-link');
    const registerLink = document.getElementById('register-link');
    const loginLink = document.getElementById('login-link');

    const tradingDashboardContainer = document.getElementById('trading-dashboard-container');
    const tradingPanelContent = document.getElementById('trading-panel-content');
    // const credentialSelectorArea = document.getElementById('credential-selector-area'); // Not used directly in this function yet

    document.querySelectorAll('.auth-dependent').forEach(el => {
        el.style.display = isLoggedIn ? '' : 'none';
    });
    document.querySelectorAll('.no-auth-dependent').forEach(el => {
        el.style.display = isLoggedIn ? 'none' : '';
    });

    if (isLoggedIn) {
        // TODO: Decode JWT to get username for profile link, or fetch from a /api/user/me endpoint
        if (profileLink) {
            profileLink.href = "/profile"; // Placeholder page
            // profileLink.textContent = `Profile (${decodedUsername})`; // Update once username is available
            profileLink.textContent = "Profile"; // Simple text for now
        }
        if (credentialsLink) credentialsLink.href = "/credentials"; // Placeholder page
        if (botsLink) botsLink.href = "/bots"; // Placeholder page

        if (logoutLink) {
            logoutLink.onclick = (e) => {
                e.preventDefault();
                console.log('Logout link clicked.');
                logoutUser(); // This will clear token and dispatch 'authChange'
            };
        }
        if (tradingDashboardContainer) tradingDashboardContainer.style.display = 'block'; // Show trading dashboard section

    } else {
        if (tradingDashboardContainer) tradingDashboardContainer.style.display = 'none';
        if (tradingPanelContent) tradingPanelContent.style.display = 'none';
    }
    console.log('[AuthUI] UI updated based on auth state. Logged In:', isLoggedIn);
}

function handleLoginFormSubmit(event) {
    event.preventDefault(); // This is crucial
    console.log('[AuthUI] Login form submission initiated by JS.');

    const form = event.target;
    const username = form.username.value;
    const password = form.password.value;
    const errorMessageElement = document.getElementById('login-error-message');

    if (!username || !password) {
        console.warn('[AuthUI] Username or password field is empty.');
        if (errorMessageElement) {
            errorMessageElement.textContent = 'Username and password are required.';
            errorMessageElement.style.display = 'block';
        }
        return;
    }

    if (errorMessageElement) errorMessageElement.style.display = 'none';
    console.log(`[AuthUI] Attempting login for user: ${username}`);

    loginUser(username, password)
        .then(token => {
            console.log('[AuthUI] Login successful from UI, token received:', !!token);
            // updateAuthUI(); // authChange event will trigger this
            // The 'authChange' event dispatched by loginUser (in dataService.js) should handle UI update.
            // Redirect to chart page or dashboard
            window.location.href = '/chart'; // Or to a user dashboard page
        })
        .catch(error => {
            console.error('[AuthUI] Login form error:', error);
            if (errorMessageElement) {
                errorMessageElement.textContent = error.message || 'Login failed. Please check your credentials.';
                errorMessageElement.style.display = 'block';
            }
            // updateAuthUI(); // Ensure UI reflects logged-out state on error
        });
}

function handleRegisterFormSubmit(event) {
    event.preventDefault(); // This is crucial
    console.log('[AuthUI] Register form submission initiated by JS.');

    const form = event.target;
    const usernameInput = form.elements['username']; // Access by name
    const emailInput = form.elements['email'];
    const passwordInput = form.elements['password'];

    // Null check for form elements
    if (!usernameInput || !emailInput || !passwordInput) {
        console.error('[AuthUI] One or more registration form elements not found.');
        // Display a generic error, or specific if possible
        const errorMessageElement = document.getElementById('register-error-message');
        if (errorMessageElement) {
            errorMessageElement.textContent = 'Registration form error. Please try again later.';
            errorMessageElement.style.display = 'block';
        }
        return;
    }


    const username = usernameInput.value;
    const email = emailInput.value;
    const password = passwordInput.value;
    const errorMessageElement = document.getElementById('register-error-message');

    if (errorMessageElement) errorMessageElement.style.display = 'none'; // Clear previous errors

    // Basic client-side validation (backend will also validate)
    if (!username || !email || !password) {
        if (errorMessageElement) {
            errorMessageElement.textContent = 'All fields are required for registration.';
            errorMessageElement.style.display = 'block';
        }
        return;
    }
    if (password.length < 8) {
         if (errorMessageElement) {
            errorMessageElement.textContent = 'Password must be at least 8 characters long.';
            errorMessageElement.style.display = 'block';
        }
        return;
    }

    console.log(`[AuthUI] Attempting registration for user: ${username}, email: ${email}`);

    registerUser(username, email, password)
        .then(responseData => {
            console.log('[AuthUI] Registration successful from UI:', responseData);
            // Assuming backend sends { message: "..." }
            alert(responseData.message || 'Registration successful! Please log in.'); // Simple alert for now
            window.location.href = '/login'; // Redirect to login page
        })
        .catch(error => {
            console.error('[AuthUI] Registration form error:', error);
            if (errorMessageElement) {
                errorMessageElement.textContent = error.message || 'Registration failed. Please try again.';
                errorMessageElement.style.display = 'block';
            }
        });
}

document.addEventListener('DOMContentLoaded', () => {
    console.log('[AuthUI] DOMContentLoaded - Initializing auth UI elements.');
    updateAuthUI(); // Initial UI setup based on stored token

    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        console.log('[AuthUI] Login form found, attaching submit listener.');
        loginForm.addEventListener('submit', handleLoginFormSubmit);
    } else {
        console.warn('[AuthUI] Login form (id="login-form") not found on this page.');
    }

    const registerForm = document.getElementById('register-form');
    if (registerForm) {
        console.log('[AuthUI] Register form found, attaching submit listener.');
        registerForm.addEventListener('submit', handleRegisterFormSubmit);
    } else {
        console.warn('[AuthUI] Register form (id="register-form") not found on this page.');
    }

    // Listen for the custom authChange event dispatched by logoutUser or successful login
    document.addEventListener('authChange', (event) => {
        console.log('[AuthUI] "authChange" event received:', event.detail);
        updateAuthUI(); // Update UI based on new auth state

        // Optional: Redirect if logged out and not on a public page
        // if (!event.detail.loggedIn &&
        //     !['/login', '/register', '/faq', '/support', '/'].includes(window.location.pathname)) {
        //     console.log('[AuthUI] User logged out, redirecting to login page.');
        //     window.location.href = '/login';
        // }
    });
});

// Optional: Make updateAuthUI globally accessible if other modules might need to trigger it
// window.appAuth = { updateAuthUI }; // Example namespacing