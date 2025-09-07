document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const uploadForm = document.getElementById('upload-form');
    const fileInput = document.getElementById('file-input');
    const uploadBtn = document.getElementById('upload-btn');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const statusAlert = document.getElementById('status-alert');
    const statusMessage = document.getElementById('status-message');
    const statusErrors = document.getElementById('status-errors');
    const statusIcon = document.getElementById('status-icon');
    const previewSection = document.getElementById('preview-section');
    const dataTableBody = document.getElementById('data-table-body');
    let previewData = [];

    // Event listeners
    uploadForm.addEventListener('submit', handleFileUpload);
    sendBtn.addEventListener('click', handleSendMessages);
    clearBtn.addEventListener('click', handleClearData);

    async function handleFileUpload(e) {
        e.preventDefault();
        
        const file = fileInput.files[0];
        if (!file) {
            showStatus('error', 'Please select a file to upload.');
            return;
        }

        // Show loading state
        setLoadingState(uploadBtn, true, 'Uploading...');
        hideStatus();

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.status === 'success') {
                showStatus('success', data.message);
                previewData = data.data;
                displayPreviewData(data.data);
                previewSection.style.display = 'block';
            } else {
                showStatus('error', data.message);
                previewSection.style.display = 'none';
            }
        } catch (error) {
            console.error('Upload error:', error);
            showStatus('error', 'An error occurred during file upload. Please try again.');
            previewSection.style.display = 'none';
        } finally {
            setLoadingState(uploadBtn, false, 'Upload & Preview');
        }
    }

    async function handleSendMessages() {
        if (!previewData.length) {
            showStatus('error', 'No data to send. Please upload a file first.');
            return;
                }
        // Show loading state
        setLoadingState(sendBtn, true, 'Sending...');
        showStatus('info', 'Sending messages to employees...');

        try {
            const response = await fetch('/send_messages', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ data: previewData })

            });

            const data = await response.json();

            if (data.status === 'success') {
                showStatus('success', data.message);
                previewSection.style.display = 'none';
                uploadForm.reset();
            } else if (data.status === 'warning') {
                showStatus('warning', data.message, data.errors);
                previewSection.style.display = 'none';
                uploadForm.reset();
            } else {
                showStatus('error', data.message, data.errors);
            }
        } catch (error) {
            console.error('Send error:', error);
            showStatus('error', 'An error occurred while sending messages. Please try again.');
        } finally {
            setLoadingState(sendBtn, false, 'Send Messages');
        }
    }

    async function handleClearData() {
        try {
            const response = await fetch('/clear_data', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (data.status === 'success') {
                previewSection.style.display = 'none';
                uploadForm.reset();
                showStatus('info', 'Data cleared successfully.');
            }
        } catch (error) {
            console.error('Clear error:', error);
            showStatus('error', 'An error occurred while clearing data.');
        }
    }

    function displayPreviewData(data) {
        dataTableBody.innerHTML = '';
        
        data.forEach((row, index) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <i class="fas fa-user text-muted me-2"></i>
                    ${escapeHtml(row.employee_name)}
                </td>
                <td>
                    <code class="text-info">${escapeHtml(row.line_user_id)}</code>
                </td>
                <td>
                    <i class="fas fa-calendar text-muted me-2"></i>
                    ${escapeHtml(row.shift_date)}
                </td>
                <td>
                    <i class="fas fa-clock text-muted me-2"></i>
                    ${escapeHtml(row.start_time)} - ${escapeHtml(row.end_time)}
                </td>
            `;
            dataTableBody.appendChild(tr);
        });
    }

    function showStatus(type, message, errors = null) {
        const alertClasses = {
            'success': 'alert-success',
            'error': 'alert-danger',
            'warning': 'alert-warning',
            'info': 'alert-info'
        };

        const iconClasses = {
            'success': 'fas fa-check-circle text-success',
            'error': 'fas fa-exclamation-circle text-danger',
            'warning': 'fas fa-exclamation-triangle text-warning',
            'info': 'fas fa-info-circle text-info'
        };

        // Reset classes
        statusAlert.className = `alert ${alertClasses[type]}`;
        statusIcon.className = iconClasses[type];
        statusMessage.textContent = message;
        
        // Handle errors
        if (errors && errors.length > 0) {
            statusErrors.innerHTML = '<strong>Details:</strong><ul class="mb-0 mt-2">' + 
                errors.map(error => `<li>${escapeHtml(error)}</li>`).join('') + 
                '</ul>';
            statusErrors.style.display = 'block';
        } else {
            statusErrors.style.display = 'none';
        }

        statusAlert.style.display = 'block';
        statusAlert.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function hideStatus() {
        statusAlert.style.display = 'none';
    }

    function setLoadingState(button, isLoading, originalText) {
        if (isLoading) {
            button.disabled = true;
            button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${originalText}`;
        } else {
            button.disabled = false;
            button.innerHTML = button.innerHTML.replace(/.*?<\/span>/, '').replace(originalText, '') + originalText;
            // Restore original icon
            if (button === uploadBtn) {
                button.innerHTML = '<i class="fas fa-cloud-upload-alt me-2"></i>' + originalText;
            } else if (button === sendBtn) {
                button.innerHTML = '<i class="fas fa-paper-plane me-2"></i>' + originalText;
            }
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Confirmation refresh functionality
    window.refreshConfirmations = async function() {
        try {
            const response = await fetch('/api/confirmations');
            const confirmations = await response.json();

            const tableBody = document.getElementById('confirmations-table-body');

            if (confirmations && confirmations.length > 0) {
                tableBody.innerHTML = confirmations.map(confirmation => `
                    <tr>
                        <td>
                            <i class="fas fa-check-circle text-success me-2"></i>
                            ${escapeHtml(confirmation.employee_name)}
                        </td>
                        <td>${escapeHtml(confirmation.confirmed_at)}</td>
                        <td>${escapeHtml(confirmation.week_start)}</td>
                        <td>
                            <span class="badge bg-success">
                                <i class="fas fa-check me-1"></i>
                                ${escapeHtml(confirmation.status)}
                            </span>
                        </td>
                    </tr>
                `).join('');
            } else {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center text-muted py-4">
                            <i class="fas fa-info-circle me-2"></i>
                            まだシフト確認がありません
                        </td>
                    </tr>
                `;
            }

            showStatus('success', '確認状況を更新しました。');
        } catch (error) {
            console.error('Refresh error:', error);
            showStatus('error', '確認状況の更新中にエラーが発生しました。');
        }
    };

    // Auto-refresh confirmations every 30 seconds
    setInterval(refreshConfirmations, 30000);
});
