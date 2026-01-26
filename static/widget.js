/**
 * LocusAI Embeddable Chat Widget
 *
 * Usage:
 * <script src="https://your-domain.com/static/widget.js"
 *         data-tenant="your-tenant-key"
 *         data-position="bottom-right"></script>
 */

(function() {
  'use strict';

  // Prevent multiple initializations
  if (window.LocusAIWidget) return;

  // Get script element and configuration
  const script = document.currentScript || document.querySelector('script[data-tenant]');

  // Determine API base URL
  let apiBase = '';
  if (script?.getAttribute('data-api-base')) {
    apiBase = script.getAttribute('data-api-base');
  } else if (window.LOCUSAI_API_BASE) {
    apiBase = window.LOCUSAI_API_BASE;
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
    console.error('LocusAI Widget: Missing data-tenant attribute');
    return;
  }

  // Widget state
  let state = {
    isOpen: false,
    isLoaded: false,
    sessionId: null,
    messages: [],
    config: null,
    pendingBooking: null,  // Current pending booking awaiting confirmation
  };

  // Storage key for session persistence
  const STORAGE_KEY = `locusai_session_${config.tenant}`;

  // ============================================================================
  // Styles
  // ============================================================================

  const styles = `
    #locusai-widget-container {
      --locusai-primary: #2f6fec;
      --locusai-primary-hover: #1d5bc7;
      --locusai-bg: #ffffff;
      --locusai-text: #1f2937;
      --locusai-text-muted: #6b7280;
      --locusai-border: #e5e7eb;
      --locusai-user-bg: var(--locusai-primary);
      --locusai-user-text: #ffffff;
      --locusai-bot-bg: #f3f4f6;
      --locusai-bot-text: #1f2937;
      position: fixed;
      bottom: 20px;
      ${config.position === 'bottom-left' ? 'left: 20px;' : 'right: 20px;'}
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }

    #locusai-launcher {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: var(--locusai-primary);
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      transition: transform 0.2s, box-shadow 0.2s;
    }

    #locusai-launcher:hover {
      transform: scale(1.05);
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
    }

    #locusai-launcher svg {
      width: 28px;
      height: 28px;
      fill: white;
    }

    #locusai-launcher.open svg.chat-icon { display: none; }
    #locusai-launcher.open svg.close-icon { display: block; }
    #locusai-launcher:not(.open) svg.chat-icon { display: block; }
    #locusai-launcher:not(.open) svg.close-icon { display: none; }

    #locusai-chat-window {
      position: absolute;
      bottom: 70px;
      ${config.position === 'bottom-left' ? 'left: 0;' : 'right: 0;'}
      width: 360px;
      max-width: calc(100vw - 40px);
      height: 500px;
      max-height: calc(100vh - 120px);
      background: var(--locusai-bg);
      border-radius: 16px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
      display: none;
      flex-direction: column;
      overflow: hidden;
      border: 1px solid var(--locusai-border);
    }

    #locusai-chat-window.open {
      display: flex;
      animation: locusai-slide-up 0.3s ease-out;
    }

    @keyframes locusai-slide-up {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    #locusai-header {
      padding: 16px;
      background: var(--locusai-primary);
      color: white;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    #locusai-header-avatar {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #locusai-header-avatar svg {
      width: 24px;
      height: 24px;
      fill: white;
    }

    #locusai-header-info {
      flex: 1;
    }

    #locusai-header-title {
      font-weight: 600;
      font-size: 16px;
    }

    #locusai-header-status {
      font-size: 12px;
      opacity: 0.9;
    }

    #locusai-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .locusai-message {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 16px;
      word-wrap: break-word;
    }

    .locusai-message.user {
      align-self: flex-end;
      background: var(--locusai-user-bg);
      color: var(--locusai-user-text);
      border-bottom-right-radius: 4px;
    }

    .locusai-message.assistant {
      align-self: flex-start;
      background: var(--locusai-bot-bg);
      color: var(--locusai-bot-text);
      border-bottom-left-radius: 4px;
    }

    .locusai-typing {
      align-self: flex-start;
      padding: 12px 16px;
      background: var(--locusai-bot-bg);
      border-radius: 16px;
      border-bottom-left-radius: 4px;
    }

    .locusai-typing-dots {
      display: flex;
      gap: 4px;
    }

    .locusai-typing-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--locusai-text-muted);
      animation: locusai-bounce 1.4s infinite ease-in-out both;
    }

    .locusai-typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .locusai-typing-dot:nth-child(2) { animation-delay: -0.16s; }

    @keyframes locusai-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }

    #locusai-input-area {
      padding: 12px 16px;
      border-top: 1px solid var(--locusai-border);
      display: flex;
      gap: 8px;
      background: var(--locusai-bg);
    }

    #locusai-input {
      flex: 1;
      padding: 10px 14px;
      border: 1px solid var(--locusai-border);
      border-radius: 24px;
      outline: none;
      font-size: 14px;
      font-family: inherit;
      resize: none;
      max-height: 100px;
      line-height: 1.4;
    }

    #locusai-input:focus {
      border-color: var(--locusai-primary);
      box-shadow: 0 0 0 2px rgba(47, 111, 236, 0.1);
    }

    #locusai-send {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: var(--locusai-primary);
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
      flex-shrink: 0;
    }

    #locusai-send:hover {
      background: var(--locusai-primary-hover);
    }

    #locusai-send:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    #locusai-send svg {
      width: 20px;
      height: 20px;
      fill: white;
    }

    #locusai-branding {
      padding: 8px;
      text-align: center;
      font-size: 11px;
      color: var(--locusai-text-muted);
      background: var(--locusai-bg);
    }

    #locusai-branding a {
      color: var(--locusai-text-muted);
      text-decoration: none;
    }

    #locusai-branding a:hover {
      text-decoration: underline;
    }

    @media (max-width: 480px) {
      #locusai-chat-window {
        width: calc(100vw - 40px);
        height: calc(100vh - 100px);
        bottom: 70px;
      }
    }

    /* Booking Confirmation Card Styles */
    .locusai-booking-card {
      background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
      border: 1px solid var(--locusai-border);
      border-radius: 12px;
      padding: 16px;
      margin: 8px 0;
      max-width: 100%;
    }

    .locusai-booking-card-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      color: var(--locusai-text);
      font-weight: 600;
      font-size: 14px;
    }

    .locusai-booking-card-header svg {
      width: 20px;
      height: 20px;
      fill: var(--locusai-primary);
    }

    .locusai-booking-details {
      background: white;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }

    .locusai-booking-row {
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid #f1f5f9;
      font-size: 13px;
    }

    .locusai-booking-row:last-child {
      border-bottom: none;
    }

    .locusai-booking-label {
      color: var(--locusai-text-muted);
    }

    .locusai-booking-value {
      color: var(--locusai-text);
      font-weight: 500;
      text-align: right;
      max-width: 60%;
      word-break: break-word;
    }

    .locusai-booking-actions {
      display: flex;
      gap: 8px;
    }

    .locusai-booking-btn {
      flex: 1;
      padding: 10px 16px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      border: none;
      transition: all 0.2s;
    }

    .locusai-booking-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .locusai-booking-btn-confirm {
      background: var(--locusai-primary);
      color: white;
    }

    .locusai-booking-btn-confirm:hover:not(:disabled) {
      background: var(--locusai-primary-hover);
    }

    .locusai-booking-btn-cancel {
      background: white;
      color: var(--locusai-text);
      border: 1px solid var(--locusai-border);
    }

    .locusai-booking-btn-cancel:hover:not(:disabled) {
      background: #f9fafb;
    }

    .locusai-booking-timer {
      text-align: center;
      font-size: 11px;
      color: var(--locusai-text-muted);
      margin-top: 8px;
    }

    .locusai-booking-confirmed {
      background: #ecfdf5;
      border-color: #a7f3d0;
    }

    .locusai-booking-confirmed .locusai-booking-card-header {
      color: #059669;
    }

    .locusai-booking-confirmed .locusai-booking-card-header svg {
      fill: #059669;
    }
  `;

  // ============================================================================
  // HTML Templates
  // ============================================================================

  const chatIcon = `<svg class="chat-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h10v2H7zm0-3h10v2H7z"/></svg>`;

  const closeIcon = `<svg class="close-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;

  const sendIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>`;

  const avatarIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`;

  const calendarIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2zm-8 4H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z"/></svg>`;

  const checkIcon = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`;

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
      console.error('LocusAI Widget API Error:', error);
      throw error;
    }
  }

  async function loadConfig() {
    try {
      const data = await apiRequest('/config');
      state.config = data;

      // Apply custom colors
      if (data.business?.accent_color) {
        const container = document.getElementById('locusai-widget-container');
        if (container) {
          container.style.setProperty('--locusai-primary', data.business.accent_color);
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

    // Clear any existing pending booking when user sends a new message
    state.pendingBooking = null;

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
      }

      // Check for pending booking that needs confirmation
      if (data.pending_booking) {
        state.pendingBooking = data.pending_booking;
        // Add a special message indicating booking needs confirmation
        state.messages.push({
          role: 'booking_confirmation',
          booking: data.pending_booking
        });
      }

      renderMessages();

    } catch (error) {
      hideTyping();
      state.messages.push({
        role: 'assistant',
        text: "I'm having trouble connecting right now. Please try again.",
      });
      renderMessages();
    }
  }

  async function confirmBooking() {
    if (!state.pendingBooking) return;

    const token = state.pendingBooking.token;
    const confirmBtn = document.getElementById('locusai-booking-confirm');
    const cancelBtn = document.getElementById('locusai-booking-cancel');

    // Disable buttons during request
    if (confirmBtn) confirmBtn.disabled = true;
    if (cancelBtn) cancelBtn.disabled = true;

    try {
      const data = await apiRequest('/booking/confirm', {
        method: 'POST',
        body: JSON.stringify({
          token: token,
          session_id: state.sessionId,
        }),
      });

      if (data.success) {
        // Update the booking card to show confirmed state
        const bookingCard = document.getElementById('locusai-booking-card');
        if (bookingCard) {
          bookingCard.classList.add('locusai-booking-confirmed');
          bookingCard.innerHTML = `
            <div class="locusai-booking-card-header">
              ${checkIcon}
              <span>Booking Confirmed!</span>
            </div>
            <div class="locusai-booking-details">
              <p style="margin: 0; color: var(--locusai-text); font-size: 13px;">
                ${escapeHtml(data.message)}
              </p>
            </div>
          `;
        }

        // Add confirmation message to chat
        state.messages.push({
          role: 'assistant',
          text: `✅ ${data.message}`
        });

        state.pendingBooking = null;
      } else {
        // Show error
        state.messages.push({
          role: 'assistant',
          text: data.message || 'Failed to confirm booking. Please try again.'
        });
        renderMessages();
      }
    } catch (error) {
      state.messages.push({
        role: 'assistant',
        text: "I couldn't confirm your booking. Please try again."
      });
      renderMessages();
    }
  }

  async function cancelBooking() {
    if (!state.pendingBooking) return;

    const token = state.pendingBooking.token;

    try {
      const data = await apiRequest('/booking/cancel', {
        method: 'POST',
        body: JSON.stringify({
          token: token,
          session_id: state.sessionId,
        }),
      });

      // Remove the booking card
      const bookingCard = document.getElementById('locusai-booking-card');
      if (bookingCard) {
        bookingCard.remove();
      }

      // Remove the booking confirmation from messages
      state.messages = state.messages.filter(m => m.role !== 'booking_confirmation');

      // Add cancellation message
      state.messages.push({
        role: 'assistant',
        text: data.message || "No problem! Let me know if you'd like to book a different time."
      });

      state.pendingBooking = null;
      renderMessages();

    } catch (error) {
      state.messages.push({
        role: 'assistant',
        text: "I couldn't cancel the booking request. Please try again."
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
    container.id = 'locusai-widget-container';
    container.innerHTML = `
      <button id="locusai-launcher" aria-label="Open chat">
        ${chatIcon}
        ${closeIcon}
      </button>
      <div id="locusai-chat-window">
        <div id="locusai-header">
          <div id="locusai-header-avatar">${avatarIcon}</div>
          <div id="locusai-header-info">
            <div id="locusai-header-title">Chat with us</div>
            <div id="locusai-header-status">We typically reply instantly</div>
          </div>
        </div>
        <div id="locusai-messages"></div>
        <div id="locusai-input-area">
          <textarea id="locusai-input" placeholder="Type a message..." rows="1"></textarea>
          <button id="locusai-send" aria-label="Send message">${sendIcon}</button>
        </div>
        <div id="locusai-branding">
          Powered by <a href="https://locusai.com" target="_blank" rel="noopener">LocusAI</a>
        </div>
      </div>
    `;

    document.body.appendChild(container);

    // Bind events
    const launcher = document.getElementById('locusai-launcher');
    const chatWindow = document.getElementById('locusai-chat-window');
    const input = document.getElementById('locusai-input');
    const sendBtn = document.getElementById('locusai-send');

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

    const launcher = document.getElementById('locusai-launcher');
    const chatWindow = document.getElementById('locusai-chat-window');

    launcher.classList.toggle('open', state.isOpen);
    chatWindow.classList.toggle('open', state.isOpen);

    if (state.isOpen) {
      // Initialize session if needed
      initSession();

      // Focus input
      setTimeout(() => {
        document.getElementById('locusai-input')?.focus();
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
    const input = document.getElementById('locusai-input');
    const text = input.value.trim();

    if (!text) return;

    input.value = '';
    input.style.height = 'auto';

    sendMessage(text);
  }

  function renderMessages() {
    const container = document.getElementById('locusai-messages');
    if (!container) return;

    container.innerHTML = state.messages.map(msg => {
      // Handle booking confirmation card
      if (msg.role === 'booking_confirmation' && msg.booking) {
        return renderBookingCard(msg.booking);
      }

      // Handle regular messages
      const roleClass = msg.role === 'assistant' ? 'assistant' : msg.role;
      return `<div class="locusai-message ${roleClass}">${escapeHtml(msg.text || '')}</div>`;
    }).join('');

    // Bind booking button events after rendering
    const confirmBtn = document.getElementById('locusai-booking-confirm');
    const cancelBtn = document.getElementById('locusai-booking-cancel');

    if (confirmBtn) {
      confirmBtn.onclick = confirmBooking;
    }
    if (cancelBtn) {
      cancelBtn.onclick = cancelBooking;
    }

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
  }

  function renderBookingCard(booking) {
    const formatDateTime = (dt) => {
      if (!dt) return 'Not specified';
      try {
        const date = new Date(dt.replace(' ', 'T'));
        return date.toLocaleString(undefined, {
          weekday: 'short',
          month: 'short',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit'
        });
      } catch (e) {
        return dt;
      }
    };

    const details = [];
    if (booking.service) {
      details.push({ label: 'Service', value: booking.service });
    }
    if (booking.datetime) {
      details.push({ label: 'Date & Time', value: formatDateTime(booking.datetime) });
    }
    if (booking.customer_name) {
      details.push({ label: 'Name', value: booking.customer_name });
    }
    if (booking.phone) {
      details.push({ label: 'Phone', value: booking.phone });
    }
    if (booking.email) {
      details.push({ label: 'Email', value: booking.email });
    }

    const detailsHtml = details.map(d => `
      <div class="locusai-booking-row">
        <span class="locusai-booking-label">${escapeHtml(d.label)}</span>
        <span class="locusai-booking-value">${escapeHtml(d.value)}</span>
      </div>
    `).join('');

    return `
      <div id="locusai-booking-card" class="locusai-booking-card">
        <div class="locusai-booking-card-header">
          ${calendarIcon}
          <span>Confirm Your Booking</span>
        </div>
        <div class="locusai-booking-details">
          ${detailsHtml}
        </div>
        <div class="locusai-booking-actions">
          <button id="locusai-booking-cancel" class="locusai-booking-btn locusai-booking-btn-cancel">
            Cancel
          </button>
          <button id="locusai-booking-confirm" class="locusai-booking-btn locusai-booking-btn-confirm">
            Confirm Booking
          </button>
        </div>
        <div class="locusai-booking-timer">
          This booking will expire in 5 minutes
        </div>
      </div>
    `;
  }

  function showTyping() {
    const container = document.getElementById('locusai-messages');
    if (!container) return;

    const typing = document.createElement('div');
    typing.className = 'locusai-typing';
    typing.id = 'locusai-typing-indicator';
    typing.innerHTML = `
      <div class="locusai-typing-dots">
        <div class="locusai-typing-dot"></div>
        <div class="locusai-typing-dot"></div>
        <div class="locusai-typing-dot"></div>
      </div>
    `;
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
  }

  function hideTyping() {
    const typing = document.getElementById('locusai-typing-indicator');
    if (typing) typing.remove();
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function updateHeader(businessName) {
    const title = document.getElementById('locusai-header-title');
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
        const input = document.getElementById('locusai-input');
        if (input) input.placeholder = configData.widget.placeholder_text;
      }

      // Hide branding if configured
      if (!configData.widget?.show_branding) {
        const branding = document.getElementById('locusai-branding');
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
  window.LocusAIWidget = {
    open: () => { if (!state.isOpen) toggleWidget(); },
    close: () => { if (state.isOpen) toggleWidget(); },
    toggle: toggleWidget,
    sendMessage: sendMessage,
  };

  // Start
  init();

})();
