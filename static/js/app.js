// AgentQueue Alpine.js global store and component definitions

document.addEventListener('alpine:init', () => {

  // Global store
  Alpine.store('agentqueue', {
    wsConnected: false,
    isIdle: false,
    activeTasks: {},
    tokenBudget: {
      pctUsed: 0,
      weeklyUsed: 0,
      weeklyLimit: 0,
      drainMode: false,
    },
    notifications: [],
    outputChunks: [],
    activeOutputTaskId: null,
    outputPanelOpen: false,

    init() {
      this.connectWebSocket();
    },

    connectWebSocket() {
      const ws = new WebSocket(`ws://${location.host}/ws/dashboard/`);

      ws.onopen = () => {
        this.wsConnected = true;
        console.log('[AgentQueue] WebSocket connected');
      };

      ws.onclose = () => {
        this.wsConnected = false;
        console.log('[AgentQueue] WebSocket disconnected, reconnecting in 3s...');
        setTimeout(() => this.connectWebSocket(), 3000);
      };

      ws.onerror = (e) => {
        console.warn('[AgentQueue] WebSocket error:', e);
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          this.handleMessage(msg);
        } catch (err) {
          console.warn('[AgentQueue] Bad WS message:', e.data);
        }
      };

      this._ws = ws;
    },

    handleMessage(msg) {
      switch (msg.type) {
        case 'task_update':
          this.activeTasks[msg.task_id] = {
            ...(this.activeTasks[msg.task_id] || {}),
            ...msg.data,
          };
          // Trigger HTMX refresh of the affected card
          const card = document.getElementById(`task-card-${msg.task_id}`);
          if (card) htmx.trigger(card, 'server:update');
          break;

        case 'budget_update':
          this.tokenBudget = { ...this.tokenBudget, ...msg.data };
          break;

        case 'idle_update':
          this.isIdle = msg.is_idle;
          break;

        case 'output_chunk':
          if (!this.activeTasks[msg.task_id]) {
            this.activeTasks[msg.task_id] = {};
          }
          const task = this.activeTasks[msg.task_id];
          task.outputLog = (task.outputLog || '') + msg.text;
          task.outputTail = msg.text.split('\n').pop();
          break;

        case 'task_complete':
          if (this.activeTasks[msg.task_id]) {
            this.activeTasks[msg.task_id].status = 'done';
          }
          break;

        case 'notification':
          this.addNotification(msg.message);
          break;
      }
    },

    addNotification(message, timeout = 5000) {
      const notification = { message, id: Date.now() };
      this.notifications.push(notification);
      setTimeout(() => {
        const idx = this.notifications.findIndex(n => n.id === notification.id);
        if (idx !== -1) this.notifications.splice(idx, 1);
      }, timeout);
    },

    openOutput(taskId) {
      this.activeOutputTaskId = taskId;
      this.outputPanelOpen = true;
      // Subscribe to task-specific WS channel
      subscribeToTaskOutput(taskId);
    },
  });

  // Per-card Alpine component
  Alpine.data('taskCard', (taskId) => ({
    taskId,
    get task() {
      return Alpine.store('agentqueue').activeTasks[taskId] || {};
    },
    get isRunning() {
      return this.task.status === 'in_progress';
    },
  }));

  // Full-page Alpine component (used on body)
  Alpine.data('agentqueue', () => ({
    notifications: [],
    isIdle: false,
    wsConnected: false,
    tokenBudget: { pctUsed: 0, drainMode: false },
    activeTasks: {},
    outputPanelOpen: false,
    activeOutputTaskId: null,

    init() {
      // Sync with store
      this.$watch('$store.agentqueue', (store) => {
        this.notifications = store.notifications;
        this.isIdle = store.isIdle;
        this.wsConnected = store.wsConnected;
        this.tokenBudget = store.tokenBudget;
      }, { immediate: true });

      Alpine.store('agentqueue').init();
    },
  }));
});

// Copy tmux attach command to clipboard
async function copyTmuxCommand(taskId) {
  try {
    const res = await fetch(`/tasks/${taskId}/tmux-attach/`);
    const data = await res.json();
    await navigator.clipboard.writeText(data.command);
    Alpine.store('agentqueue').addNotification(`Copied: ${data.command}`);
  } catch (e) {
    console.warn('copyTmuxCommand failed:', e);
  }
}

// Subscribe to task-specific output WebSocket
let taskWs = null;
function subscribeToTaskOutput(taskId) {
  if (taskWs) taskWs.close();
  taskWs = new WebSocket(`ws://${location.host}/ws/tasks/${taskId}/`);
  taskWs.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    Alpine.store('agentqueue').handleMessage(msg);
  };
}
