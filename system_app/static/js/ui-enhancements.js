// UI/UX Enhancements - Toast Notifications, Loading States, Confirmation Dialogs, etc.

// ==================== Toast Notification System ====================
class ToastManager {
    constructor() {
        this.container = null;
        this.init();
    }

    init() {
        // Create toast container
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        `;
        document.body.appendChild(this.container);
    }

    show(message, type = 'info', duration = 5000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };

        const colors = {
            success: '#4caf50',
            error: '#f44336',
            warning: '#ff9800',
            info: '#2196F3'
        };

        toast.style.cssText = `
            background: rgba(30, 30, 40, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid ${colors[type]}40;
            border-left: 4px solid ${colors[type]};
            color: white;
            padding: 16px 20px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            gap: 12px;
            animation: slideInRight 0.3s ease;
            cursor: pointer;
            min-width: 300px;
        `;

        toast.innerHTML = `
            <span style="font-size: 20px;">${icons[type] || icons.info}</span>
            <span style="flex: 1; font-size: 14px; line-height: 1.5;">${message}</span>
            <button class="toast-close" style="background: none; border: none; color: #888; cursor: pointer; font-size: 18px; padding: 0; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;">&times;</button>
        `;

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => this.remove(toast));
        
        // Auto remove
        if (duration > 0) {
            setTimeout(() => this.remove(toast), duration);
        }

        this.container.appendChild(toast);

        // Click to dismiss
        toast.addEventListener('click', (e) => {
            if (e.target.classList.contains('toast-close')) return;
            this.remove(toast);
        });

        return toast;
    }

    remove(toast) {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }

    success(message, duration = 5000) {
        return this.show(message, 'success', duration);
    }

    error(message, duration = 5000) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration = 5000) {
        return this.show(message, 'warning', duration);
    }

    info(message, duration = 5000) {
        return this.show(message, 'info', duration);
    }
}

// Initialize toast manager
const toast = new ToastManager();

// Convert flash messages to toasts
document.addEventListener('DOMContentLoaded', function() {
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        const category = msg.classList.contains('error') ? 'error' : 
                        msg.classList.contains('warning') ? 'warning' : 
                        msg.classList.contains('info') ? 'info' : 'success';
        const message = msg.textContent.trim();
        if (message) {
            toast[category](message);
            msg.style.display = 'none'; // Hide original flash message
        }
    });
});

// ==================== Loading States ====================
class LoadingManager {
    show(element, text = 'Loading...') {
        if (typeof element === 'string') {
            element = document.querySelector(element);
        }
        
        if (!element) return null;

        const loader = document.createElement('div');
        loader.className = 'loading-overlay';
        loader.innerHTML = `
            <div class="loading-spinner">
                <div class="spinner"></div>
                <p>${text}</p>
            </div>
        `;
        loader.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(5px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            border-radius: inherit;
        `;

        const spinner = loader.querySelector('.spinner');
        spinner.style.cssText = `
            width: 50px;
            height: 50px;
            border: 4px solid rgba(76, 175, 80, 0.3);
            border-top: 4px solid #4caf50;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 15px;
        `;

        loader.querySelector('p').style.cssText = `
            color: #4caf50;
            font-size: 16px;
            font-weight: 600;
            margin: 0;
        `;

        const parent = element.parentElement || document.body;
        if (parent.style.position === 'static' || !parent.style.position) {
            parent.style.position = 'relative';
        }
        parent.appendChild(loader);

        return loader;
    }

    hide(loader) {
        if (loader && loader.parentNode) {
            loader.parentNode.removeChild(loader);
        }
    }

    showButton(button, text = 'Loading...') {
        if (typeof button === 'string') {
            button = document.querySelector(button);
        }
        if (!button) return;

        button.dataset.originalText = button.textContent;
        button.disabled = true;
        button.innerHTML = `<span class="button-spinner"></span> ${text}`;
        
        const spinner = button.querySelector('.button-spinner');
        spinner.style.cssText = `
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top: 2px solid white;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        `;
    }

    hideButton(button) {
        if (typeof button === 'string') {
            button = document.querySelector(button);
        }
        if (!button) return;

        button.disabled = false;
        button.textContent = button.dataset.originalText || button.textContent;
    }
}

const loading = new LoadingManager();

// ==================== Confirmation Dialogs ====================
class ConfirmDialog {
    show(message, title = 'Confirm', type = 'warning') {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'confirm-overlay';
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                backdrop-filter: blur(5px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                animation: fadeIn 0.2s ease;
            `;

            const dialog = document.createElement('div');
            dialog.className = 'confirm-dialog';
            dialog.style.cssText = `
                background: rgba(30, 30, 40, 0.95);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(76, 175, 80, 0.3);
                border-radius: 16px;
                padding: 30px;
                max-width: 500px;
                width: 90%;
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
                animation: slideUp 0.3s ease;
            `;

            const icons = {
                danger: '🔴',
                warning: '⚠️',
                info: 'ℹ️',
                success: '✅'
            };

            const colors = {
                danger: '#f44336',
                warning: '#ff9800',
                info: '#2196F3',
                success: '#4caf50'
            };

            dialog.innerHTML = `
                <div style="text-align: center; margin-bottom: 20px;">
                    <div style="font-size: 48px; margin-bottom: 15px;">${icons[type] || icons.warning}</div>
                    <h3 style="color: ${colors[type] || colors.warning}; margin: 0 0 15px 0; font-size: 24px;">${title}</h3>
                    <p style="color: #ccc; font-size: 16px; line-height: 1.6; margin: 0;">${message}</p>
                </div>
                <div style="display: flex; gap: 15px; justify-content: center;">
                    <button class="confirm-btn confirm-cancel" style="
                        background: rgba(100, 100, 100, 0.3);
                        color: white;
                        border: 1px solid rgba(100, 100, 100, 0.5);
                        padding: 12px 24px;
                        border-radius: 8px;
                        cursor: pointer;
                        font-size: 16px;
                        font-weight: 600;
                        transition: all 0.3s;
                    ">Cancel</button>
                    <button class="confirm-btn confirm-ok" style="
                        background: linear-gradient(135deg, ${colors[type] || colors.warning}, ${colors[type] || colors.warning}dd);
                        color: white;
                        border: none;
                        padding: 12px 24px;
                        border-radius: 8px;
                        cursor: pointer;
                        font-size: 16px;
                        font-weight: 600;
                        transition: all 0.3s;
                    ">Confirm</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Button handlers
            dialog.querySelector('.confirm-cancel').addEventListener('click', () => {
                this.close(overlay);
                resolve(false);
            });

            dialog.querySelector('.confirm-ok').addEventListener('click', () => {
                this.close(overlay);
                resolve(true);
            });

            // Close on overlay click
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    this.close(overlay);
                    resolve(false);
                }
            });

            // ESC key
            const escHandler = (e) => {
                if (e.key === 'Escape') {
                    this.close(overlay);
                    resolve(false);
                    document.removeEventListener('keydown', escHandler);
                }
            };
            document.addEventListener('keydown', escHandler);
        });
    }

    close(overlay) {
        overlay.style.animation = 'fadeOut 0.2s ease';
        setTimeout(() => {
            if (overlay.parentNode) {
                overlay.parentNode.removeChild(overlay);
            }
        }, 200);
    }
}

const confirmDialog = new ConfirmDialog();

// Helper function for easy confirmation
function confirmAction(message, title = 'Confirm Action') {
    return confirmDialog.show(message, title, 'warning');
}

// ==================== Form Validation ====================
function setupFormValidation() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        const inputs = form.querySelectorAll('input[required], textarea[required], select[required]');
        
        inputs.forEach(input => {
            // Real-time validation
            input.addEventListener('blur', function() {
                validateField(this);
            });

            input.addEventListener('input', function() {
                if (this.classList.contains('invalid')) {
                    validateField(this);
                }
            });
        });

        // Form submission validation
        form.addEventListener('submit', function(e) {
            let isValid = true;
            inputs.forEach(input => {
                if (!validateField(input)) {
                    isValid = false;
                }
            });

            if (!isValid) {
                e.preventDefault();
                toast.error('Please fix the errors in the form');
                const firstInvalid = form.querySelector('.invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                    firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        });
    });
}

function validateField(field) {
    const value = field.value.trim();
    let isValid = true;
    let errorMessage = '';

    // Remove previous error
    const existingError = field.parentElement.querySelector('.field-error');
    if (existingError) {
        existingError.remove();
    }
    field.classList.remove('invalid', 'valid');

    // Required validation
    if (field.hasAttribute('required') && !value) {
        isValid = false;
        errorMessage = 'This field is required';
    }

    // Email validation
    if (field.type === 'email' && value) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) {
            isValid = false;
            errorMessage = 'Please enter a valid email address';
        }
    }

    // Phone validation
    if (field.type === 'tel' && value) {
        const phoneRegex = /^[\d\s\-\+\(\)]+$/;
        if (!phoneRegex.test(value)) {
            isValid = false;
            errorMessage = 'Please enter a valid phone number';
        }
    }

    // Number validation
    if (field.type === 'number' && value) {
        if (isNaN(value)) {
            isValid = false;
            errorMessage = 'Please enter a valid number';
        }
    }

    // Min/Max length
    if (field.hasAttribute('minlength') && value.length < parseInt(field.getAttribute('minlength'))) {
        isValid = false;
        errorMessage = `Minimum ${field.getAttribute('minlength')} characters required`;
    }

    if (field.hasAttribute('maxlength') && value.length > parseInt(field.getAttribute('maxlength'))) {
        isValid = false;
        errorMessage = `Maximum ${field.getAttribute('maxlength')} characters allowed`;
    }

    // Show error or success
    if (!isValid) {
        field.classList.add('invalid');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'field-error';
        errorDiv.textContent = errorMessage;
        errorDiv.style.cssText = `
            color: #f44336;
            font-size: 12px;
            margin-top: 5px;
            display: flex;
            align-items: center;
            gap: 5px;
        `;
        field.parentElement.appendChild(errorDiv);
    } else if (value) {
        field.classList.add('valid');
    }

    return isValid;
}

// ==================== Keyboard Shortcuts ====================
function setupKeyboardShortcuts() {
    // Ctrl+K or / for search
    document.addEventListener('keydown', function(e) {
        // Ignore if typing in input/textarea
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
                return; // Allow / in inputs
            }
        }

        // Ctrl+K or Cmd+K for quick search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.querySelector('#member_id, #member_name, input[type="search"]');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
        }

        // ? for help
        if (e.key === '?' && !e.ctrlKey && !e.metaKey && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            e.preventDefault();
            showKeyboardShortcutsHelp();
        }

        // ESC to close modals
        if (e.key === 'Escape') {
            const modals = document.querySelectorAll('.confirm-overlay, .modal-overlay');
            modals.forEach(modal => {
                if (modal.style.display !== 'none') {
                    modal.click();
                }
            });
        }
    });
}

function showKeyboardShortcutsHelp() {
    const shortcuts = [
        { key: 'Ctrl+K', desc: 'Quick search' },
        { key: '?', desc: 'Show keyboard shortcuts' },
        { key: 'Esc', desc: 'Close dialogs/modals' },
    ];

    const helpText = shortcuts.map(s => `${s.key}: ${s.desc}`).join('\n');
    toast.info(helpText, 5000);
}

// ==================== Search Autocomplete ====================
function setupSearchAutocomplete() {
    const searchInputs = document.querySelectorAll('#member_name, #member_id, input[name="member_name"], input[name="member_id"]');
    
    searchInputs.forEach(input => {
        let autocompleteList = null;
        let selectedIndex = -1;

        input.addEventListener('input', async function(e) {
            const query = this.value.trim();
            
            if (query.length < 2) {
                if (autocompleteList) {
                    autocompleteList.remove();
                    autocompleteList = null;
                }
                return;
            }

            // Create autocomplete list
            if (!autocompleteList) {
                autocompleteList = document.createElement('div');
                autocompleteList.className = 'autocomplete-list';
                autocompleteList.style.cssText = `
                    position: absolute;
                    top: 100%;
                    left: 0;
                    right: 0;
                    background: rgba(30, 30, 40, 0.95);
                    backdrop-filter: blur(20px);
                    border: 1px solid rgba(76, 175, 80, 0.3);
                    border-radius: 8px;
                    margin-top: 5px;
                    max-height: 300px;
                    overflow-y: auto;
                    z-index: 1000;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                `;
                this.parentElement.style.position = 'relative';
                this.parentElement.appendChild(autocompleteList);
            }

            // Fetch suggestions from API
            try {
                autocompleteList.innerHTML = '<div style="padding: 15px; color: #888; text-align: center;">Searching...</div>';
                
                const response = await fetch(`/api/search/members?q=${encodeURIComponent(query)}&limit=5`);
                if (!response.ok) throw new Error('Search failed');
                
                const suggestions = await response.json();
                
                if (suggestions.length === 0) {
                    autocompleteList.innerHTML = '<div style="padding: 15px; color: #888; text-align: center;">No members found</div>';
                    return;
                }

                autocompleteList.innerHTML = suggestions.map((member, index) => `
                    <div class="autocomplete-item" data-index="${index}" data-id="${member.id}" data-name="${member.name}">
                        <div style="font-weight: 600; color: #fff; margin-bottom: 4px;">${member.name}</div>
                        <div style="font-size: 12px; color: #888;">
                            ${member.phone ? '📱 ' + member.phone : ''} 
                            ${member.status ? ' | Status: ' + member.status : ''}
                        </div>
                    </div>
                `).join('');

                // Add click handlers
                autocompleteList.querySelectorAll('.autocomplete-item').forEach(item => {
                    item.addEventListener('click', function() {
                        const memberId = this.dataset.id;
                        const memberName = this.dataset.name;
                        
                        if (input.id.includes('id') || input.name.includes('id')) {
                            input.value = memberId;
                        } else {
                            input.value = memberName;
                        }
                        
                        autocompleteList.remove();
                        autocompleteList = null;
                        selectedIndex = -1;
                        
                        // Auto-submit if single result
                        if (suggestions.length === 1) {
                            const form = input.closest('form');
                            if (form) {
                                setTimeout(() => form.submit(), 300);
                            }
                        }
                    });
                });
            } catch (error) {
                console.error('Autocomplete error:', error);
                autocompleteList.innerHTML = '<div style="padding: 15px; color: #f44336; text-align: center;">Error loading suggestions</div>';
            }
        });

        // Keyboard navigation
        input.addEventListener('keydown', function(e) {
            if (!autocompleteList) return;

            const items = autocompleteList.querySelectorAll('.autocomplete-item');
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                updateSelection(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, -1);
                updateSelection(items);
            } else if (e.key === 'Enter' && selectedIndex >= 0) {
                e.preventDefault();
                items[selectedIndex].click();
            } else if (e.key === 'Escape') {
                if (autocompleteList) {
                    autocompleteList.remove();
                    autocompleteList = null;
                }
            }
        });

        function updateSelection(items) {
            items.forEach((item, index) => {
                if (index === selectedIndex) {
                    item.style.background = 'rgba(76, 175, 80, 0.2)';
                } else {
                    item.style.background = 'transparent';
                }
            });
        }

        // Close on outside click
        document.addEventListener('click', function(e) {
            if (!input.contains(e.target) && autocompleteList && !autocompleteList.contains(e.target)) {
                autocompleteList.remove();
                autocompleteList = null;
            }
        });
    });
}

// ==================== Theme Toggle ====================
function setupThemeToggle() {
    // Get saved theme or default to dark
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    // Create theme toggle button
    const themeToggle = document.createElement('button');
    themeToggle.id = 'theme-toggle';
    themeToggle.innerHTML = savedTheme === 'dark' ? '☀️' : '🌙';
    themeToggle.title = 'Toggle theme';
    themeToggle.style.cssText = `
        background: rgba(30, 30, 40, 0.8);
        border: 1px solid rgba(76, 175, 80, 0.3);
        color: white;
        padding: 8px 12px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 18px;
        transition: all 0.3s;
        position: fixed;
        top: 20px;
        right: 80px;
        z-index: 1000;
    `;

    themeToggle.addEventListener('click', function() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        this.innerHTML = newTheme === 'dark' ? '☀️' : '🌙';
        toast.info(`Switched to ${newTheme} theme`);
    });

    // Add to header if it exists
    const header = document.querySelector('header .user-info, header .header-content');
    if (header) {
        header.appendChild(themeToggle);
    } else {
        document.body.appendChild(themeToggle);
    }
}

// ==================== Scroll to Top Button ====================
function setupScrollToTop() {
    const scrollBtn = document.createElement('button');
    scrollBtn.id = 'scroll-to-top';
    scrollBtn.innerHTML = '↑';
    scrollBtn.title = 'Scroll to top';
    scrollBtn.style.cssText = `
        position: fixed;
        bottom: 100px;
        right: 20px;
        width: 50px;
        height: 50px;
        background: linear-gradient(135deg, #4caf50, #66d66a);
        color: white;
        border: none;
        border-radius: 50%;
        font-size: 24px;
        cursor: pointer;
        box-shadow: 0 4px 15px rgba(76, 175, 80, 0.4);
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s;
        z-index: 999;
    `;

    document.body.appendChild(scrollBtn);

    window.addEventListener('scroll', function() {
        if (window.pageYOffset > 300) {
            scrollBtn.style.opacity = '1';
            scrollBtn.style.visibility = 'visible';
        } else {
            scrollBtn.style.opacity = '0';
            scrollBtn.style.visibility = 'hidden';
        }
    });

    scrollBtn.addEventListener('click', function() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
}

// ==================== Initialize Everything ====================
document.addEventListener('DOMContentLoaded', function() {
    setupFormValidation();
    setupKeyboardShortcuts();
    setupSearchAutocomplete();
    setupThemeToggle();
    setupScrollToTop();

    // Add CSS animations
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideInRight {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        @keyframes slideOutRight {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        @keyframes fadeOut {
            from { opacity: 1; }
            to { opacity: 0; }
        }

        @keyframes slideUp {
            from {
                transform: translateY(20px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }

        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        .toast:hover {
            transform: translateX(-5px);
        }

        .confirm-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        }

        input.invalid {
            border-color: #f44336 !important;
            box-shadow: 0 0 20px rgba(244, 67, 54, 0.3) !important;
        }

        input.valid {
            border-color: #4caf50 !important;
            box-shadow: 0 0 20px rgba(76, 175, 80, 0.3) !important;
        }

        #scroll-to-top:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(76, 175, 80, 0.6);
        }

        /* Light theme styles */
        [data-theme="light"] {
            --bg-primary: #f5f5f5;
            --bg-secondary: #ffffff;
            --text-primary: #1a1a1a;
            --text-secondary: #666;
            --border-color: #e0e0e0;
        }

        [data-theme="light"] body {
            background: linear-gradient(135deg, #f5f5f5 0%, #e8e8e8 50%, #ffffff 100%);
            color: var(--text-primary);
        }

        [data-theme="light"] .action-card,
        [data-theme="light"] .stat-item,
        [data-theme="light"] .nav-btn {
            background: rgba(255, 255, 255, 0.9);
            color: var(--text-primary);
            border-color: var(--border-color);
        }
    `;
    document.head.appendChild(style);
});

// Export for use in other scripts
window.toast = toast;
window.loading = loading;
window.confirmDialog = confirmDialog;
window.confirmAction = confirmAction;

