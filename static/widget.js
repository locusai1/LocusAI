/**
 * AxisAI Embeddable Chat Widget
 *
 * Usage:
 * <script src="https://your-domain.com/static/widget.js"
 *         data-tenant="your-tenant-key"
 *         data-position="bottom-right"></script>
 */

(function() {
  'use strict';

  // Prevent multiple initializations
  if (window.AxisAIWidget) return;

  // Get script element and configuration
  const script = document.currentScript || document.querySelector('script[data-tenant]');

  // Determine API base URL
  let apiBase = '';
  if (script?.getAttribute('data-api-base')) {
    apiBase = script.getAttribute('data-api-base');
  } else if (window.AXISAI_API_BASE) {
    apiBase = window.AXISAI_API_BASE;
  } else if (script?.src) {
    // Extract base URL from script src
    const srcUrl = new URL(script.src, window.location.href);
    apiBase = srcUrl.origin;
  } else {
    // Fallback to current origin
    apiBase = window.location.origin;
  }

  const config = {
    tenant: script?.getAttribute('data-tenant') || '',
    position: script?.getAttribute('data-position') || 'bottom-right',
    apiBase: apiBase.replace(/\/$/, ''), // Remove trailing slash
  };

  if (!config.tenant) {
    console.error('AxisAI Widget: Missing data-tenant attribute');
    return;
  }

  // Widget state
  let state = {
    isOpen: false,
    isLoaded: false,
    sessionId: null,
    messages: [],
    config: null,
  };

  // Storage key for session persistence
  const STORAGE_KEY = `axisai_session_${config.tenant}`;

  // ============================================================================
  // Styles
  // ============================================================================

  const styles = `
    #axisai-widget-container {
      --axisai-primary: #2f6fec;
      --axisai-primary-hover: #1d5bc7;
      --axisai-bg: #ffffff;
      --axisai-text: #1f2937;
      --axisai-text-muted: #6b7280;
      --axisai-border: #e5e7eb;
      --axisai-user-bg: var(--axisai-primary);
      --axisai-user-text: #ffffff;
      --axisai-bot-bg: #f3f4f6;
      --axisai-bot-text: #1f2937;
      position: fixed;
      bottom: 20px;
      ${config.position === 'bottom-left' ? 'left: 20px;' : 'right: 20px;'}
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }

    #axisai-launcher {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: var(--axisai-primary);
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      transition: transform 0.2s, box-shadow 0.2s;
    }

    #axisai-launcher:hover {
      transform: scale(1.05);
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
    }

    #axisai-launcher svg {
      width: 28px;
      height: 28px;
      fill: white;
    }

    #axisai-launcher.open svg.chat-icon { display: none; }
    #axisai-launcher.open svg.close-icon { display: block; }
    #axisai-launcher:not(.open) svg.chat-icon { display: block; }
    #axisai-launcher:not(.open) svg.close-icon { display: none; }

    #axisai-chat-window {
      position: absolute;
      bottom: 70px;
      ${config.position === 'bottom-left' ? 'left: 0;' : 'right: 0;'}
      width: 360px;
      max-width: calc(100vw - 40px);
      height: 500px;
      max-height: calc(100vh - 120px);
      background: var(--axisai-bg);
      border-radius: 16px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
      display: none;
      flex-direction: column;
      overflow: hidden;
      border: 1px solid var(--axisai-border);
    }

    #axisai-chat-window.open {
      display: flex;
      animation: axisai-slide-up 0.3s ease-out;
    }

    @keyframes axisai-slide-up {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    #axisai-header {
      padding: 16px;
      background: var(--axisai-primary);
      color: white;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    #axisai-header-avatar {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #axisai-header-avatar svg {
      width: 24px;
      height: 24px;
      fill: white;
    }

    #axisai-header-info {
      flex: 1;
    }

    #axisai-header-title {
      font-weight: 600;
      font-size: 16px;
    }

    #axisai-header-status {
      font-size: 12px;
      opacity: 0.9;
    }

    #axisai-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .axisai-message {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 16px;
      word-wrap: break-word;
    }

    .axisai-message.user {
      align-self: flex-end;
      background: var(--axisai-user-bg);
      color: var(--axisai-user-text);
      border-bottom-right-radius: 4px;
    }

    .axisai-message.assistant {
      align-self: flex-start;
      background: var(--axisai-bot-bg);
      color: var(--axisai-bot-text);
      border-bottom-left-radius: 4px;
    }

    .axisai-typing {
      align-self: flex-start;
      padding: 12px 16px;
      background: var(--axisai-bot-bg);
      border-radius: 16px;
      border-bottom-left-radius: 4px;
    }

    .axisai-typing-dots {
      display: flex;
      gap: 4px;
    }

    .axisai-typing-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--axisai-text-muted);
      animation: axisai-bounce 1.4s infinite ease-in-out both;
    }

    .axisai-typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .axisai-typing-dot:nth-child(2) { animation-delay: -0.16s; }

    @keyframes axisai-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }

    #axisai-input-area {
      padding: 12px 16px;
      border-top: 1px solid var(--axisai-border);
      display: flex;
      gap: 8px;
      background: var(--axisai-bg);
    }

    #axisai-input {
      flex: 1;
      padding: 10px 14px;
      border: 1px solid var(--axisai-border);
      border-radius: 24px;
      outline: none;
      font-size: 14px;
      font-family: inherit;
      resize: none;
      max-height: 100px;
      line-height: 1.4;
    }

    #axisai-input:focus {
      border-color: var(--axisai-primary);
      box-shadow: 0 0 0 2px rgba(47, 111, 236, 0.1);
    }

    #axisai-send {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: var(--axisai-primary);
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
      flex-shrink: 0;
    }

    #axisai-send:hover {
      background: var(--axisai-primary-hover);
    }

    #axisai-send:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    #axisai-send svg {
      width: 20px;
      height: 20px;
      fill: white;
    }

    #axisai-branding {
      padding: 8px;
      text-align: center;
      font-size: 11px;
      color: var(--axisai-text-muted);
      background: var(--axisai-bg);
    }

    #axisai-branding a {
      color: var(--axisai-text-muted);
      text-decoration: none;
    }

    #axisai-branding a:hover {
      text-decoration: underline;
    }

    @media (max-width: 480px) {
      #axisai-chat-window {
        width: calc(100vw - 40px);
        height: calc(100vh - 100px);
        bottom: 70px;
      }
    }
  `;

  // ============================================================================
  // HTML Templates
  // ============================================================================

  const chatIcon = `<svg class="chat-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h10v2H7zm0-3h10v2H7z"/></svg>`;

  const closeIcon = `<svg class="close-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;

  const sendIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>`;

  const avatarIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`;

  // ============================================================================
  // API Functions
  // ============================================================================

  async function apiRequest(endpoint, options = {}) {
    const url = `${config.apiBase}/api/widget${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      'X-Tenant-Key': config.tenant,
      ...options.headers,
    };

    if (state.sessionId) {
      headers['X-Session-ID'] = state.sessionId;
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('AxisAI Widget API Error:', error);
      throw error;
    }
  }

  async function loadConfig() {
    try {
      const data = await apiRequest('/config');
      state.config = data;

      // Apply custom colors
      if (data.business?.accent_color) {
        const container = document.getElementById('axisai-widget-container');
        if (container) {
          container.style.setProperty('--axisai-primary', data.business.accent_color);
        }
      }

      return data;
    } catch (error) {
      console.error('Failed to load widget config:', error);
      return null;
    }
  }

  async function createSession() {
    try {
      const data = await apiRequest('/session', { method: 'POST' });
      state.sessionId = data.session_id;

      // Save to localStorage
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          sessionId: data.session_id,
          timestamp: Date.now(),
        }));
      } catch (e) {}

      // Add welcome message
      if (data.welcome_message) {
        state.messages.push({
          role: 'assistant',
          text: data.welcome_message,
        });
        renderMessages();
      }

      return data;
    } catch (error) {
      console.error('Failed to create session:', error);
      return null;
    }
  }

  async function loadHistory() {
    if (!state.sessionId) return;

    try {
      const data = await apiRequest('/history');
      if (data.messages?.length) {
        state.messages = data.messages;
        renderMessages();
      }
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  }

  async function sendMessage(text) {
    if (!text.trim()) return;

    // Add user message to UI immediately
    state.messages.push({ role: 'user', text: text.trim() });
    renderMessages();

    // Show typing indicator
    showTyping();

    try {
      const data = await apiRequest('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: text.trim(),
          session_id: state.sessionId,
        }),
      });

      hideTyping();

      // Add bot response
      if (data.reply) {
        state.messages.push({ role: 'assistant', text: data.reply });
        renderMessages();
      }
    } catch (error) {
      hideTyping();
      state.messages.push({
        role: 'assistant',
        text: "I'm having trouble connecting right now. Please try again.",
      });
      renderMessages();
    }
  }

  // ============================================================================
  // UI Functions
  // ============================================================================

  function createWidget() {
    // Inject styles
    const styleEl = document.createElement('style');
    styleEl.textContent = styles;
    document.head.appendChild(styleEl);

    // Create container
    const container = document.createElement('div');
    container.id = 'axisai-widget-container';
    container.innerHTML = `
      <button id="axisai-launcher" aria-label="Open chat">
        ${chatIcon}
        ${closeIcon}
      </button>
      <div id="axisai-chat-window">
        <div id="axisai-header">
          <div id="axisai-header-avatar">${avatarIcon}</div>
          <div id="axisai-header-info">
            <div id="axisai-header-title">Chat with us</div>
            <div id="axisai-header-status">We typically reply instantly</div>
          </div>
        </div>
        <div id="axisai-messages"></div>
        <div id="axisai-input-area">
          <textarea id="axisai-input" placeholder="Type a message..." rows="1"></textarea>
          <button id="axisai-send" aria-label="Send message">${sendIcon}</button>
        </div>
        <div id="axisai-branding">
          Powered by <a href="https://axisai.com" target="_blank" rel="noopener">AxisAI</a>
        </div>
      </div>
    `;

    document.body.appendChild(container);

    // Bind events
    const launcher = document.getElementById('axisai-launcher');
    const chatWindow = document.getElementById('axisai-chat-window');
    const input = document.getElementById('axisai-input');
    const sendBtn = document.getElementById('axisai-send');

    launcher.addEventListener('click', toggleWidget);

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    input.addEventListener('input', () => {
      // Auto-resize textarea
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 100) + 'px';
    });

    sendBtn.addEventListener('click', handleSend);

    state.isLoaded = true;
  }

  function toggleWidget() {
    state.isOpen = !state.isOpen;

    const launcher = document.getElementById('axisai-launcher');
    const chatWindow = document.getElementById('axisai-chat-window');

    launcher.classList.toggle('open', state.isOpen);
    chatWindow.classList.toggle('open', state.isOpen);

    if (state.isOpen) {
      // Initialize session if needed
      initSession();

      // Focus input
      setTimeout(() => {
        document.getElementById('axisai-input')?.focus();
      }, 100);
    }
  }

  async function initSession() {
    if (state.sessionId) return;

    // Try to restore from localStorage
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const data = JSON.parse(stored);
        // Check if session is less than 24 hours old
        if (data.sessionId && Date.now() - data.timestamp < 24 * 60 * 60 * 1000) {
          state.sessionId = data.sessionId;
          await loadHistory();
          return;
        }
      }
    } catch (e) {}

    // Create new session
    await createSession();
  }

  function handleSend() {
    const input = document.getElementById('axisai-input');
    const text = input.value.trim();

    if (!text) return;

    input.value = '';
    input.style.height = 'auto';

    sendMessage(text);
  }

  function renderMessages() {
    const container = document.getElementById('axisai-messages');
    if (!container) return;

    container.innerHTML = state.messages.map(msg => `
      <div class="axisai-message ${msg.role}">${escapeHtml(msg.text)}</div>
    `).join('');

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
  }

  function showTyping() {
    const container = document.getElementById('axisai-messages');
    if (!container) return;

    const typing = document.createElement('div');
    typing.className = 'axisai-typing';
    typing.id = 'axisai-typing-indicator';
    typing.innerHTML = `
      <div class="axisai-typing-dots">
        <div class="axisai-typing-dot"></div>
        <div class="axisai-typing-dot"></div>
        <div class="axisai-typing-dot"></div>
      </div>
    `;
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
  }

  function hideTyping() {
    const typing = document.getElementById('axisai-typing-indicator');
    if (typing) typing.remove();
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function updateHeader(businessName) {
    const title = document.getElementById('axisai-header-title');
    if (title && businessName) {
      title.textContent = businessName;
    }
  }

  // ============================================================================
  // Initialization
  // ============================================================================

  async function init() {
    // Wait for DOM
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
      return;
    }

    // Create widget UI
    createWidget();

    // Load config and apply customizations
    const configData = await loadConfig();
    if (configData) {
      updateHeader(configData.business?.name);

      // Apply placeholder
      if (configData.widget?.placeholder_text) {
        const input = document.getElementById('axisai-input');
        if (input) input.placeholder = configData.widget.placeholder_text;
      }

      // Hide branding if configured
      if (!configData.widget?.show_branding) {
        const branding = document.getElementById('axisai-branding');
        if (branding) branding.style.display = 'none';
      }

      // Auto-open after delay
      if (configData.widget?.auto_open_delay && !state.isOpen) {
        setTimeout(() => {
          if (!state.isOpen) toggleWidget();
        }, configData.widget.auto_open_delay * 1000);
      }
    }
  }

  // Expose API for programmatic control
  window.AxisAIWidget = {
    open: () => { if (!state.isOpen) toggleWidget(); },
    close: () => { if (state.isOpen) toggleWidget(); },
    toggle: toggleWidget,
    sendMessage: sendMessage,
  };

  // Start
  init();

})();
