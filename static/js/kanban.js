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
        const newOrder = evt.newIndex;

        if (!taskId || !newStatus) return;

        const data = new FormData();
        data.append('task_id', taskId);
        data.append('new_status', newStatus);
        data.append('new_order', newOrder);
        data.append('csrfmiddlewaretoken', getCsrfToken());

        htmx.ajax('POST', '/tasks/reorder/', {
          values: {
            task_id: taskId,
            new_status: newStatus,
            new_order: newOrder,
            csrfmiddlewaretoken: getCsrfToken(),
          }
        });
      },
    });
  });
}

function getCsrfToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value
    || document.cookie.match(/csrftoken=([^;]+)/)?.[1]
    || '';
}
