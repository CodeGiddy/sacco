// Mobile menu toggle
function setupMobileMenu() {
    const nav = document.querySelector('.navbar');
    const navLinksWrapper = document.querySelector('.nav-links-wrapper');
    const burger = document.querySelector('.burger');

    // Create burger if it doesn't already exist
    if (!burger.innerHTML.trim()) {
        burger.innerHTML = `<span></span><span></span><span></span>`;
    }

    burger.addEventListener('click', () => {
        navLinksWrapper.classList.toggle('nav-active'); // Toggle menu visibility
    });
}

// Admin Notifications
function addNotifications() {
    document.getElementById('notification').style.display = 'block';
}

function removeNotifications() {
    document.getElementById('notification').style.display = 'none';
}

// Messages Report
function openReplyModal() {
    document.getElementById('replyModal').style.display = 'block';
}

function closeReplyModal() {
    document.getElementById('replyModal').style.display = 'none';
}

// Member Page Functions //

// Personal Details
function toggleForm() {
    var form = document.getElementById('updateForm');
    if (form.style.display === 'none' || form.style.display === '') {
        form.style.display = 'block'; // Show the form
    } else {
        form.style.display = 'none'; // Hide the form
    }
}

function toggleFormPassword() {
    var form = document.getElementById('changePassword');
    if (form.style.display === 'none' || form.style.display === '') {
        form.style.display = 'block'; // Show the form
    } else {
        form.style.display = 'none'; // Hide the form
    }
}

// Deposit Form
if (document.getElementById('depositForm')) {
    document.getElementById('depositForm').addEventListener('submit', function(event) {
        var amount = parseFloat(document.getElementById('amount').value);
        var errorMessage = document.getElementById('error-message');
        var maxErrorMessage = document.getElementById('max-error-message');

        if (amount < 50) {
            event.preventDefault();
            errorMessage.style.display = 'block';
        } else if (amount > 100000) {
            event.preventDefault();
            maxErrorMessage.style.display = 'block';
        } else {
            errorMessage.style.display = 'none';
            maxErrorMessage.style.display = 'none';
        }
    });
}

function validatePasswords() {
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm_password').value;

    if (password.length < 8) {
        alert('Password must be at least 8 characters long.');
        return false; // Prevent form submission
    }

    if (password !== confirmPassword) {
        alert('Passwords do not match.');
        return false; // Prevent form submission
    }

    return true; // Allow form submission
}

// Initialize All Functions //

document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.navbar')) setupMobileMenu();
});
