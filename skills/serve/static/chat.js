/**
 * LLM Wiki - Chat Sidebar JavaScript
 * Handles WebSocket connection, message rendering, and reconnection logic
 */

(function() {
    'use strict';

    // ========================================================================
    // Configuration
    // ========================================================================

    const RECONNECT_DELAY = 3000;
    const MAX_RECONNECT_ATTEMPTS = 10;

    // ========================================================================
    // State
    // ========================================================================

    let ws = null;
    let reconnectAttempts = 0;
    let pageUrl = window.location.pathname;

    // DOM Elements
    const chatMessagesDiv = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const chatSendBtn = document.getElementById('chat-send');
    const chatStatus = document.getElementById('chat-status');
    const chatToggle = document.querySelector('.wiki-chat-toggle');
    const chatWidget = document.getElementById('chat-widget');
    const connectionDot = document.getElementById('connection-indicator');

    // ========================================================================
    // Connection Management
    // ========================================================================

    function connect() {
        // Determine WebSocket protocol
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = protocol + '//' + window.location.host + '/ws/chat';

        try {
            ws = new WebSocket(wsUrl);

            ws.addEventListener('open', onWebSocketOpen);
            ws.addEventListener('message', onWebSocketMessage);
            ws.addEventListener('error', onWebSocketError);
            ws.addEventListener('close', onWebSocketClose);
        } catch (error) {
            console.error('WebSocket connection error:', error);
            updateConnectionStatus('disconnected');
            scheduleReconnect();
        }
    }

    function onWebSocketOpen(event) {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus('connected');
    }

    function onWebSocketMessage(event) {
        try {
            const data = JSON.parse(event.data);
            // Server sends {type: "response"|"error"|"context_updated", content: "..."}
            if (data.type === 'response' && data.content) {
                renderMessage({ role: 'assistant', content: data.content });
            } else if (data.type === 'error' && data.content) {
                renderMessage({ role: 'assistant', content: '(error) ' + data.content });
            }
            // Auto-scroll to bottom
            chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
        } catch (error) {
            console.error('Error parsing message:', error);
        }
    }

    function onWebSocketError(event) {
        console.error('WebSocket error:', event);
        updateConnectionStatus('disconnected');
    }

    function onWebSocketClose(event) {
        console.log('WebSocket closed');
        updateConnectionStatus('disconnected');
        scheduleReconnect();
    }

    function scheduleReconnect() {
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            if (chatStatus) {
                chatStatus.textContent = 'Reconnecting (' + reconnectAttempts + '/' + MAX_RECONNECT_ATTEMPTS + ')...';
            }
            setTimeout(connect, RECONNECT_DELAY * Math.min(reconnectAttempts, 3));
        } else {
            if (chatStatus) {
                chatStatus.textContent = 'Connection lost. Refresh to retry.';
            }
        }
    }

    function updateConnectionStatus(status) {
        if (status === 'connected') {
            if (chatStatus) {
                chatStatus.textContent = '';
                chatStatus.className = 'wiki-chat-status connected';
            }
            if (connectionDot) {
                connectionDot.style.background = '#28a745';
                connectionDot.title = 'Connected';
            }
            if (chatInput) chatInput.disabled = false;
            if (chatSendBtn) chatSendBtn.disabled = false;
        } else {
            if (chatStatus) {
                chatStatus.textContent = '';
                chatStatus.className = 'wiki-chat-status disconnected';
            }
            if (connectionDot) {
                connectionDot.style.background = '#dc3545';
                connectionDot.title = 'Disconnected';
            }
            // Don't disable input - let user try to send anyway
        }
    }

    // ========================================================================
    // Message Rendering
    // ========================================================================

    function renderMessage(messageData) {
        const {
            role = 'assistant',
            content = '',
            timestamp = null
        } = messageData;

        // Remove typing indicator if present
        removeTypingIndicator();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'wiki-chat-message ' + role;

        // Parse and render markdown-ish content
        const renderedContent = renderMarkdown(content);
        messageDiv.innerHTML = renderedContent;

        chatMessagesDiv.appendChild(messageDiv);

        // Smooth scroll to bottom
        chatMessagesDiv.scrollTo({
            top: chatMessagesDiv.scrollHeight,
            behavior: 'smooth'
        });
    }

    function showTypingIndicator() {
        removeTypingIndicator();
        const indicator = document.createElement('div');
        indicator.className = 'wiki-chat-message assistant wiki-typing-indicator';
        indicator.innerHTML = '<span class="wiki-loading-inline"></span> Thinking...';
        indicator.style.opacity = '0.7';
        indicator.style.fontSize = '0.85em';
        chatMessagesDiv.appendChild(indicator);
        chatMessagesDiv.scrollTo({ top: chatMessagesDiv.scrollHeight, behavior: 'smooth' });
    }

    function removeTypingIndicator() {
        var indicator = chatMessagesDiv.querySelector('.wiki-typing-indicator');
        if (indicator) indicator.remove();
    }

    function renderMarkdown(text) {
        // Escape HTML
        text = text.replace(/&/g, '&amp;')
                   .replace(/</g, '&lt;')
                   .replace(/>/g, '&gt;');

        // Bold: **text** -> <strong>text</strong>
        text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Italic: *text* -> <em>text</em>
        text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Inline code: `code` -> <code>code</code>
        text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Links: [text](url) -> <a href="url">text</a>
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

        // Line breaks: \n -> <br>
        text = text.replace(/\n/g, '<br>');

        return text;
    }

    // ========================================================================
    // Message Sending
    // ========================================================================

    function sendMessage() {
        const content = chatInput.value.trim();

        if (!content) {
            return;
        }

        if (!ws || ws.readyState !== WebSocket.OPEN) {
            console.warn('WebSocket not connected');
            // Still try to send via HTTP fallback
            sendViaHTTP(content);
            return;
        }

        // Send user message
        const userMessage = {
            role: 'user',
            content: content
        };

        renderMessage(userMessage);
        chatInput.value = '';
        showTypingIndicator();

        // Send to server via WebSocket (server expects {type: "message", content: "..."})
        ws.send(JSON.stringify({
            type: 'message',
            content: content
        }));
    }

    function sendViaHTTP(content) {
        // Show user message immediately
        renderMessage({ role: 'user', content: content });
        if (chatInput) chatInput.value = '';
        showTypingIndicator();

        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: content,
                page_url: pageUrl
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.response) {
                renderMessage({
                    role: 'assistant',
                    content: data.response
                });
                if (chatMessagesDiv) chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
            } else if (data.error) {
                renderMessage({
                    role: 'assistant',
                    content: '(error) ' + data.error
                });
            }
        })
        .catch(error => {
            console.error('HTTP send error:', error);
            renderMessage({
                role: 'assistant',
                content: '(error) Could not reach server'
            });
        });
    }

    // ========================================================================
    // Event Listeners
    // ========================================================================

    // Send button
    if (chatSendBtn) {
        chatSendBtn.addEventListener('click', function(e) {
            e.preventDefault();
            sendMessage();
        });
    }

    // Enter key
    if (chatInput) {
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Chat toggle handled by base.html inline script (header click expands/collapses body)

    // ========================================================================
    // Page Navigation & Reconnection
    // ========================================================================

    // Store current page URL
    function updatePageUrl() {
        pageUrl = window.location.pathname;
    }

    // Listen for navigation (if using SPA-style navigation)
    window.addEventListener('popstate', function(e) {
        updatePageUrl();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'context',
                page: pageUrl,
                title: document.title
            }));
        }
    });

    // Fallback: Check page URL periodically
    setInterval(function() {
        const newUrl = window.location.pathname;
        if (newUrl !== pageUrl) {
            updatePageUrl();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    action: 'navigate',
                    page_url: pageUrl
                }));
            }
        }
    }, 1000);

    // ========================================================================
    // Initialize
    // ========================================================================

    function init() {
        console.log('Chat sidebar script loaded');
        connect();

        // Load chat history (optional, server-side persistence)
        loadChatHistory();
    }

    function loadChatHistory() {
        fetch('/api/chat/history')
            .then(response => response.json())
            .then(data => {
                if (data.messages && Array.isArray(data.messages)) {
                    data.messages.forEach(msg => {
                        renderMessage(msg);
                    });
                    chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
                }
            })
            .catch(error => {
                console.log('No chat history available');
            });
    }

    // Start on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
