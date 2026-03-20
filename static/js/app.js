// AgentQueue — Alpine.js stores and global utilities

document.addEventListener('alpine:init', () => {

  Alpine.store('agentqueue', {
    wsConnected: false,
    isIdle: false,
    activeTasks: {},   // task_id -> { status, outputLog, outputTail }
    tokenBudget: {
      pctUsed: 0,
      weeklyUsed: 0,
      weeklyLimit: 0,
      drainMode: false,
    },
    notifications: [],
    _ws: null,
    _reconnectDelay: 1000,

    _pollInterval: null,

    init() {
      this._connect();
      // Poll immediately to populate initial task state (badge counts etc.)
      // then continue every 10s as a WS fallback
      this._poll();
      this._pollInterval = setInterval(() => this._poll(), 10000);
    },

    _poll() {
      if (this.wsConnected) return; // WS is handling updates
      fetch('/api/poll/')
        .then(r => r.json())
        .then(data => {
          if (!data.tasks) return;
          let changed = false;

          // Remove stale in_progress entries no longer in poll results
          // (task completed/failed while WS was down)
          for (const [id, info] of Object.entries(this.activeTasks)) {
            if (info.status === 'in_progress' && !data.tasks[id]) {
              delete this.activeTasks[id];
              changed = true;
            }
          }

          for (const [id, info] of Object.entries(data.tasks)) {
            const existing = this.activeTasks[id] || {};
            const prev = existing.status;
            this.activeTasks[id] = { ...existing, ...info };
            if (prev && info.status !== prev) {
              changed = true;
              window.dispatchEvent(new CustomEvent('task-status-changed', {
                detail: { taskId: id, from: prev, to: info.status }
              }));
            }
          }
          if (changed) this._refreshColumnCounts();
        })
        .catch(() => {}); // silently fail
    },

    _connect() {
      if (this._ws && this._ws.readyState < 2) return;

      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${location.host}/ws/dashboard/`);

      ws.onopen = () => {
        if (!this.wsConnected && this._wasConnected) {
          this.notify('Reconnected to server', 'success');
        }
        this.wsConnected = true;
        this._wasConnected = true;
        this._reconnectDelay = 1000;
      };
      ws.onclose = () => {
        const wasConnected = this.wsConnected;
        this.wsConnected = false;
        if (wasConnected) {
          this.notify('Live connection lost — reconnecting...', 'error', 4000);
        }
        this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, 15000);
        setTimeout(() => this._connect(), this._reconnectDelay);
      };
      ws.onerror = () => { this.wsConnected = false; };
      ws.onmessage = (e) => {
        try { this._handle(JSON.parse(e.data)); } catch (_) {}
      };

      this._ws = ws;
    },

    _handle(msg) {
      switch (msg.type) {
        case 'task_update': {
          const existing = this.activeTasks[msg.task_id] || {};
          const prev = existing.status;
          this.activeTasks[msg.task_id] = { ...existing, ...msg.data };
          const card = document.getElementById(`task-card-${msg.task_id}`);
          if (card) htmx.trigger(card, 'server:update');

          // If status changed, show a toast + desktop notification
          const newStatus = msg.data?.status;
          if (newStatus && prev && newStatus !== prev) {
            const title = msg.data?.title || `Task #${msg.task_id}`;
            if (newStatus === 'done') {
              this.notify(`"${title}" completed`, 'success');
              this._desktopNotify('Task Completed', `"${title}" finished successfully.`);
              this._playSound('success');
            } else if (newStatus === 'failed') {
              this.notify(`"${title}" failed`, 'error');
              this._desktopNotify('Task Failed', `"${title}" encountered an error.`);
              this._playSound('error');
            } else if (newStatus === 'in_progress') {
              this.notify(`"${title}" started running`, 'info');
            }
          }

          // Move card to correct kanban column if status changed
          if (newStatus && prev && newStatus !== prev && card) {
            this._moveCardToColumn(card, newStatus);
            // Flash animation on completion
            if (newStatus === 'done') {
              card.classList.add('done-flash');
              setTimeout(() => card.classList.remove('done-flash'), 700);
            }
          }

          // Refresh column counts on the kanban board
          this._refreshColumnCounts();

          // Notify task list page of status changes
          if (newStatus && prev && newStatus !== prev) {
            window.dispatchEvent(new CustomEvent('task-status-changed', { detail: { taskId: msg.task_id, from: prev, to: newStatus } }));
          }
          break;
        }
        case 'budget_update': {
          this.tokenBudget = { ...this.tokenBudget, ...msg.data };
          break;
        }
        case 'idle_update': {
          this.isIdle = msg.is_idle;
          break;
        }
        case 'output_chunk': {
          if (!this.activeTasks[msg.task_id]) this.activeTasks[msg.task_id] = {};
          const t = this.activeTasks[msg.task_id];
          t.outputLog = (t.outputLog || '') + msg.text;
          const lines = msg.text.split('\n').filter(l => l.trim());
          if (lines.length) t.outputTail = lines[lines.length - 1];
          // Auto-scroll is handled by x-ref in the global output panel (base.html)
          break;
        }
        case 'task_complete': {
          if (!this.activeTasks[msg.task_id]) this.activeTasks[msg.task_id] = {};
          this.activeTasks[msg.task_id].status = 'done';
          // Refresh the card to show done state
          const doneCard = document.getElementById(`task-card-${msg.task_id}`);
          if (doneCard) htmx.trigger(doneCard, 'server:update');
          break;
        }
        case 'notification': {
          this.notify(msg.message);
          if (msg.suggestions) {
            window.dispatchEvent(new CustomEvent('suggestion-ready', {
              detail: { suggestions: msg.suggestions, projectId: msg.project_id }
            }));
          }
          break;
        }
      }
    },

    _moveCardToColumn(card, newStatus) {
      // Map status to kanban column: failed/paused → backlog, cancelled → remove
      const columnMap = {
        'backlog': 'column-backlog',
        'scheduled': 'column-scheduled',
        'in_progress': 'column-in_progress',
        'done': 'column-done',
        'failed': 'column-backlog',
        'paused': 'column-backlog',
      };
      const targetId = columnMap[newStatus];
      if (!targetId) {
        // cancelled — hide the card
        card.style.display = 'none';
        return;
      }
      const targetCol = document.getElementById(targetId);
      if (!targetCol || card.closest(`#${targetId}`)) return; // already in correct column
      // Remove empty-state placeholder if present
      const emptyState = targetCol.querySelector('.border-dashed');
      if (emptyState) emptyState.remove();
      targetCol.prepend(card);
    },

    _refreshColumnCounts() {
      // Update kanban column badges from DOM counts (visible cards only)
      document.querySelectorAll('.kanban-column').forEach(col => {
        const count = Array.from(col.querySelectorAll('.task-card')).filter(c => c.style.display !== 'none').length;
        const badge = col.parentElement?.querySelector('[data-column-count]');
        if (badge) badge.textContent = count;
      });
    },

    notify(message, type = 'info', ms = 6000) {
      const id = Date.now() + Math.random();
      this.notifications.push({ id, message, type });
      setTimeout(() => {
        const idx = this.notifications.findIndex(n => n.id === id);
        if (idx !== -1) this.notifications.splice(idx, 1);
      }, ms);
    },

    _playSound(type) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        gain.gain.value = 0.08;
        if (type === 'success') {
          osc.frequency.value = 880;
          osc.type = 'sine';
          gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
        } else {
          osc.frequency.value = 330;
          osc.type = 'triangle';
          gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
        }
        osc.start();
        osc.stop(ctx.currentTime + 0.5);
      } catch (_) {}
    },

    _desktopNotify(title, body) {
      if (!('Notification' in window)) return;
      if (Notification.permission === 'granted') {
        new Notification(title, { body, icon: '/static/img/favicon.svg' });
      } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(p => {
          if (p === 'granted') new Notification(title, { body, icon: '/static/img/favicon.svg' });
        });
      }
    },
  });

});  // end alpine:init


// ---- Global helpers ----

async function copyTmuxCommand(taskId) {
  try {
    const res = await fetch(`/tasks/${taskId}/tmux-attach/`);
    const data = await res.json();
    await navigator.clipboard.writeText(data.command);
    Alpine.store('agentqueue').notify('Copied: ' + data.command, 'success');
  } catch (_) {
    Alpine.store('agentqueue').notify('Could not copy command.', 'error');
  }
}

// Per-task WebSocket for live output (opened when output panel opens)
let _taskWs = null;
function subscribeToTaskOutput(taskId) {
  if (_taskWs) { _taskWs.close(); _taskWs = null; }
  if (!taskId) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  _taskWs = new WebSocket(`${proto}//${location.host}/ws/tasks/${taskId}/`);
  _taskWs.onmessage = (e) => {
    try { Alpine.store('agentqueue')._handle(JSON.parse(e.data)); } catch (_) {}
  };
  _taskWs.onclose = () => { _taskWs = null; };
}

// Boot: init store once Alpine is ready
document.addEventListener('alpine:initialized', () => {
  Alpine.store('agentqueue').init();
});

// ---- HTMX loading indicator ----
// Show a top progress bar during HTMX requests
(function() {
  let bar = null;
  let hideTimer = null;

  function getBar() {
    if (!bar) {
      bar = document.getElementById('htmx-progress-bar');
    }
    return bar;
  }

  document.body.addEventListener('htmx:beforeRequest', function () {
    const b = getBar();
    if (b) {
      clearTimeout(hideTimer);
      b.style.width = '0%';
      b.style.opacity = '1';
      b.style.transition = 'none';
      requestAnimationFrame(() => {
        b.style.transition = 'width 8s cubic-bezier(0.1, 0.5, 0.1, 1)';
        b.style.width = '85%';
      });
    }
  });

  document.body.addEventListener('htmx:afterRequest', function () {
    const b = getBar();
    if (b) {
      b.style.transition = 'width 0.2s ease-out';
      b.style.width = '100%';
      hideTimer = setTimeout(() => {
        b.style.transition = 'opacity 0.3s ease';
        b.style.opacity = '0';
      }, 200);
    }
  });
})();

// ---- HTMX error handling ----
// Fires when server returns 4xx / 5xx
document.body.addEventListener('htmx:responseError', function (evt) {
  // If the response includes HX-Trigger with agentqueue:error, that handler fires separately.
  // Avoid double-toasting by checking for the trigger header.
  try {
    const trigger = evt.detail.xhr.getResponseHeader('HX-Trigger');
    if (trigger && JSON.parse(trigger)['agentqueue:error']) return;
  } catch (_) {}
  let msg = 'Something went wrong.';
  try {
    const data = JSON.parse(evt.detail.xhr.responseText);
    if (data.error) msg = data.error;
  } catch (_) {}
  Alpine.store('agentqueue').notify(msg, 'error');
});

// Fires when the request can't reach the server at all
document.body.addEventListener('htmx:sendError', function () {
  Alpine.store('agentqueue').notify('Network error — could not reach the server.', 'error');
});

// Fires via HX-Trigger: {"agentqueue:error": {"message": "..."}}
document.body.addEventListener('agentqueue:error', function (evt) {
  const msg = evt.detail?.message || 'An error occurred.';
  Alpine.store('agentqueue').notify(msg, 'error');
});

// Fires via HX-Trigger: {"agentqueue:success": {"message": "..."}}
document.body.addEventListener('agentqueue:success', function (evt) {
  const msg = evt.detail?.message || 'Done.';
  Alpine.store('agentqueue').notify(msg, 'success');
});

// Fires via HX-Trigger: {"agentqueue:undo": {"message": "...", "undo_url": "/tasks/123/restore/"}}
document.body.addEventListener('agentqueue:undo', function (evt) {
  const msg = evt.detail?.message || 'Action completed';
  const undoUrl = evt.detail?.undo_url;
  const store = Alpine.store('agentqueue');
  const id = Date.now() + Math.random();
  store.notifications.push({ id, message: msg, type: 'undo', undoUrl });
  setTimeout(() => {
    const idx = store.notifications.findIndex(n => n.id === id);
    if (idx !== -1) store.notifications.splice(idx, 1);
  }, 8000);
});

// Auto-close modal after successful task creation
document.body.addEventListener('agentqueue:modal-close', function () {
  document.querySelectorAll('[x-data]').forEach(el => {
    try {
      const data = Alpine.$data(el);
      if (data && data.modalOpen !== undefined) data.modalOpen = false;
    } catch (_) {}
  });
});

// ---- Keyboard shortcuts ----
document.addEventListener('keydown', function (e) {
  // Don't trigger shortcuts when typing in form fields
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;

  // n = New task — handled by Alpine @keydown.n.window on dashboard/task list pages
  // No global fallback needed (Alpine handles it per-page)

  // / = Focus search (on task list page)
  if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
    const searchInput = document.querySelector('input[x-model="search"]');
    if (searchInput) { searchInput.focus(); e.preventDefault(); }
  }

  // j/k = Navigate task rows
  if ((e.key === 'j' || e.key === 'k') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const rows = Array.from(document.querySelectorAll('[data-task-row]')).filter(r => r.style.display !== 'none');
    if (!rows.length) return;
    const current = document.querySelector('[data-task-row].ring-1');
    let idx = current ? rows.indexOf(current) : -1;
    if (e.key === 'j') idx = Math.min(idx + 1, rows.length - 1);
    else idx = Math.max(idx - 1, 0);
    rows.forEach(r => r.classList.remove('ring-1', 'ring-indigo-500/50'));
    rows[idx].classList.add('ring-1', 'ring-indigo-500/50');
    rows[idx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    e.preventDefault();
  }

  // Enter = Open focused task row
  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
    const focused = document.querySelector('[data-task-row].ring-1');
    if (focused) { focused.click(); e.preventDefault(); }
  }

  // r = Run focused task (task list page only — detail page handles this via Alpine)
  if (e.key === 'r' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const focused = document.querySelector('[data-task-row].ring-1');
    if (focused) {
      const runBtn = focused.querySelector('[hx-post*="trigger"]');
      if (runBtn) { runBtn.click(); e.preventDefault(); }
    }
    // Note: detail page handles R via @keydown.r.window in detail.html
  }

  // e = Edit focused task row (task list page only — detail page handles this via Alpine)
  if (e.key === 'e' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const focused = document.querySelector('[data-task-row].ring-1');
    if (focused) {
      // Open the focused task's detail page
      focused.click(); e.preventDefault();
    }
    // Note: detail page handles E via @keydown.e.window in detail.html
  }

  // d = Dashboard
  if (e.key === 'd' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (location.pathname !== '/') { window.location = '/'; e.preventDefault(); }
  }

  // t = Tasks list
  if (e.key === 't' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (!location.pathname.startsWith('/tasks')) { window.location = '/tasks/'; e.preventDefault(); }
  }

  // p = Projects
  if (e.key === 'p' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (!location.pathname.startsWith('/projects')) { window.location = '/projects/'; e.preventDefault(); }
  }

  // s = Schedule
  if (e.key === 's' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (!location.pathname.startsWith('/scheduling')) { window.location = '/scheduling/'; e.preventDefault(); }
  }

  // ? = Keyboard shortcuts panel is handled by Alpine in base.html
});

// ---- Live relative time (timeago) ----
(function() {
  function timeAgo(date) {
    const now = Date.now();
    const diff = now - date.getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 5) return 'just now';
    if (seconds < 60) return seconds + ' seconds ago';
    const minutes = Math.floor(seconds / 60);
    if (minutes === 1) return '1 minute ago';
    if (minutes < 60) return minutes + ' minutes ago';
    const hours = Math.floor(minutes / 60);
    if (hours === 1) return '1 hour ago';
    if (hours < 24) return hours + ' hours ago';
    const days = Math.floor(hours / 24);
    if (days === 1) return '1 day ago';
    if (days < 30) return days + ' days ago';
    return date.toLocaleDateString();
  }

  function updateAll() {
    document.querySelectorAll('[data-timeago]').forEach(el => {
      const d = new Date(el.dataset.timeago);
      if (!isNaN(d)) el.textContent = timeAgo(d);
    });
  }

  // Update every 30s
  setInterval(updateAll, 30000);
  // Initial pass after DOM is ready
  document.addEventListener('DOMContentLoaded', updateAll);
  // Re-run after HTMX swaps
  document.body.addEventListener('htmx:afterSwap', () => setTimeout(updateAll, 50));
})();

// ---- Favicon badge for running tasks ----
(function() {
  const defaultFavicon = '/static/img/favicon.svg';
  let currentBadgeCount = -1;

  function updateFaviconBadge() {
    if (typeof Alpine === 'undefined' || !Alpine.store('agentqueue')) return;
    const active = Alpine.store('agentqueue').activeTasks;
    const running = Object.values(active).filter(t => t.status === 'in_progress').length;

    if (running === currentBadgeCount) return;
    currentBadgeCount = running;

    if (running === 0) {
      setFavicon(defaultFavicon);
      return;
    }

    // Draw badge on canvas
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 64;
    const ctx = canvas.getContext('2d');

    // Draw base circle
    ctx.beginPath();
    ctx.arc(32, 32, 30, 0, 2 * Math.PI);
    const grad = ctx.createLinearGradient(0, 0, 64, 64);
    grad.addColorStop(0, '#312E81');
    grad.addColorStop(1, '#6D28D9');
    ctx.fillStyle = grad;
    ctx.fill();

    // Badge circle
    ctx.beginPath();
    ctx.arc(50, 14, 14, 0, 2 * Math.PI);
    ctx.fillStyle = '#F59E0B';
    ctx.fill();

    // Badge text
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 16px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(running > 9 ? '9+' : String(running), 50, 15);

    setFavicon(canvas.toDataURL('image/png'));
  }

  function setFavicon(href) {
    let link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.href = href;
  }

  // Also update the page title with running task count
  const baseTitle = document.title;
  function updateTitle() {
    if (typeof Alpine === 'undefined' || !Alpine.store('agentqueue')) return;
    const active = Alpine.store('agentqueue').activeTasks;
    const running = Object.values(active).filter(t => t.status === 'in_progress').length;
    document.title = running > 0 ? `(${running} running) ${baseTitle}` : baseTitle;
  }

  document.addEventListener('alpine:initialized', () => {
    setInterval(() => { updateFaviconBadge(); updateTitle(); }, 2000);
  });
})();
