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

    init() {
      this._connect();
    },

    _connect() {
      if (this._ws && this._ws.readyState < 2) return;

      const ws = new WebSocket(`ws://${location.host}/ws/dashboard/`);

      ws.onopen = () => { this.wsConnected = true; };
      ws.onclose = () => {
        this.wsConnected = false;
        setTimeout(() => this._connect(), 3000);
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
          this.activeTasks[msg.task_id] = { ...existing, ...msg.data };
          const card = document.getElementById(`task-card-${msg.task_id}`);
          if (card) htmx.trigger(card, 'server:update');
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
          const container = document.getElementById('output-scroll-container');
          if (container) requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
          break;
        }
        case 'task_complete': {
          if (!this.activeTasks[msg.task_id]) this.activeTasks[msg.task_id] = {};
          this.activeTasks[msg.task_id].status = 'done';
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

    notify(message, ms = 6000) {
      const id = Date.now();
      this.notifications.push({ id, message });
      setTimeout(() => {
        const idx = this.notifications.findIndex(n => n.id === id);
        if (idx !== -1) this.notifications.splice(idx, 1);
      }, ms);
    },
  });

});  // end alpine:init


// ---- Global helpers ----

async function copyTmuxCommand(taskId) {
  try {
    const res = await fetch(`/tasks/${taskId}/tmux-attach/`);
    const data = await res.json();
    await navigator.clipboard.writeText(data.command);
    Alpine.store('agentqueue').notify(`Copied: ${data.command}`);
  } catch (_) {
    Alpine.store('agentqueue').notify('Could not copy command.');
  }
}

// Per-task WebSocket for live output (opened when output panel opens)
let _taskWs = null;
function subscribeToTaskOutput(taskId) {
  if (_taskWs) { _taskWs.close(); _taskWs = null; }
  if (!taskId) return;
  _taskWs = new WebSocket(`ws://${location.host}/ws/tasks/${taskId}/`);
  _taskWs.onmessage = (e) => {
    try { Alpine.store('agentqueue')._handle(JSON.parse(e.data)); } catch (_) {}
  };
  _taskWs.onclose = () => { _taskWs = null; };
}

// Boot: init store once Alpine is ready
document.addEventListener('alpine:initialized', () => {
  Alpine.store('agentqueue').init();
});
