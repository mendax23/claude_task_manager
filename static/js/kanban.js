// SortableJS Kanban drag-and-drop

document.addEventListener('DOMContentLoaded', () => {
  initKanban();
});

function initKanban() {
  document.querySelectorAll('.kanban-column').forEach(column => {
    new Sortable(column, {
      group: 'kanban',
      animation: 200,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      handle: '.task-card',
      delay: 100,
      delayOnTouchOnly: true,

      onEnd(evt) {
        const taskId = evt.item.dataset.taskId;
        const newStatus = evt.to.dataset.status;
        const oldStatus = evt.from.dataset.status;
        const newOrder = evt.newIndex;

        if (!taskId || !newStatus) return;

        htmx.ajax('POST', '/tasks/reorder/', {
          values: {
            task_id: taskId,
            new_status: newStatus,
            new_order: newOrder,
            csrfmiddlewaretoken: getCsrfToken(),
          }
        });

        // Dragged into In Progress from another column → ask to run now
        if (newStatus === 'in_progress' && oldStatus !== 'in_progress') {
          const title = evt.item.querySelector('p')?.textContent?.trim() || '';
          window.dispatchEvent(new CustomEvent('kanban:trigger-confirm', {
            detail: { taskId, taskTitle: title }
          }));
        }
      },
    });
  });
}

function getCsrfToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value
    || document.cookie.match(/csrftoken=([^;]+)/)?.[1]
    || '';
}

function triggerTask(taskId) {
  htmx.ajax('POST', `/tasks/${taskId}/trigger/`, {
    target: `#task-card-${taskId}`,
    swap: 'outerHTML',
    values: { csrfmiddlewaretoken: getCsrfToken() },
  });
}
