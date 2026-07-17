const PAGE_SIZE = 20;
const SORT_FIELDS = new Set([
  'project_id', 'review_version', 'copy_from_version', 'state', 'task_type',
  'score', 'critical_issue_count', 'issue_count', 'create_time',
]);
const DESCENDING_FIRST = new Set(['score', 'critical_issue_count', 'issue_count', 'create_time']);
const TYPE_VALUES = new Set(['1', '2']);
const STATE_VALUES = new Set(['0', '1', '2', '3', '4']);

const defaultState = () => ({
  projectId: '', reviewVersion: '', dateFrom: '', dateTo: '', taskType: '', taskState: '',
  sortBy: 'create_time', sortOrder: 'desc', page: 1,
});
let viewState = defaultState();
let activeRequest = null;

const $ = (selector) => document.querySelector(selector);
const formatNumber = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const formatDateTime = (value) => value
  ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(value))
  : '--';

function readStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const sortBy = params.get('sort_by');
  const sortOrder = params.get('sort_order');
  const page = Number(params.get('page'));
  const taskType = params.get('task_type') || '';
  const taskState = params.get('state') || '';
  viewState = {
    projectId: params.get('project_id') || '',
    reviewVersion: params.get('review_version') || '',
    dateFrom: validDateInput(params.get('date_from')),
    dateTo: validDateInput(params.get('date_to')),
    taskType: TYPE_VALUES.has(taskType) ? taskType : '',
    taskState: STATE_VALUES.has(taskState) ? taskState : '',
    sortBy: SORT_FIELDS.has(sortBy) ? sortBy : 'create_time',
    sortOrder: ['asc', 'desc'].includes(sortOrder) ? sortOrder : 'desc',
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

function validDateInput(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value : '';
}

function syncForm() {
  $('#project-filter').value = viewState.projectId;
  $('#version-filter').value = viewState.reviewVersion;
  $('#date-from-filter').value = viewState.dateFrom;
  $('#date-to-filter').value = viewState.dateTo;
  $('#type-filter').value = viewState.taskType;
  $('#state-filter').value = viewState.taskState;
}

function browserParams() {
  const params = new URLSearchParams();
  if (viewState.projectId) params.set('project_id', viewState.projectId);
  if (viewState.reviewVersion) params.set('review_version', viewState.reviewVersion);
  if (viewState.dateFrom) params.set('date_from', viewState.dateFrom);
  if (viewState.dateTo) params.set('date_to', viewState.dateTo);
  if (viewState.taskType) params.set('task_type', viewState.taskType);
  if (viewState.taskState) params.set('state', viewState.taskState);
  if (viewState.sortBy !== 'create_time') params.set('sort_by', viewState.sortBy);
  if (viewState.sortOrder !== 'desc') params.set('sort_order', viewState.sortOrder);
  if (viewState.page !== 1) params.set('page', String(viewState.page));
  return params;
}

function updateBrowserUrl(mode) {
  if (mode === 'none') return;
  const params = browserParams();
  const url = `${window.location.pathname}${params.size ? `?${params}` : ''}`;
  window.history[mode === 'push' ? 'pushState' : 'replaceState']({}, '', url);
}

function localBoundary(dateValue, endOfDay = false) {
  if (!dateValue) return '';
  const [year, month, day] = dateValue.split('-').map(Number);
  const value = endOfDay
    ? new Date(year, month - 1, day, 23, 59, 59, 999)
    : new Date(year, month - 1, day, 0, 0, 0, 0);
  return value.toISOString();
}

function apiParams() {
  const params = new URLSearchParams({
    page: String(viewState.page),
    page_size: String(PAGE_SIZE),
    sort_by: viewState.sortBy,
    sort_order: viewState.sortOrder,
  });
  if (viewState.projectId) params.set('project_id', viewState.projectId);
  if (viewState.reviewVersion) params.set('review_version', viewState.reviewVersion);
  if (viewState.dateFrom) params.set('date_from', localBoundary(viewState.dateFrom));
  if (viewState.dateTo) params.set('date_to', localBoundary(viewState.dateTo, true));
  if (viewState.taskType) params.set('task_type', viewState.taskType);
  if (viewState.taskState) params.set('state', viewState.taskState);
  return params;
}

async function loadTasks({ historyMode = 'replace' } = {}) {
  updateBrowserUrl(historyMode);
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  setLoading(true);
  try {
    const response = await fetch(`/api/admin/tasks?${apiParams()}`, {
      cache: 'no-store', signal: request.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${response.status}`);
    }
    const result = await response.json();
    if (result.pagination.page !== viewState.page) {
      viewState.page = result.pagination.page;
      updateBrowserUrl('replace');
    }
    renderResult(result);
    $('#error-state').hidden = true;
  } catch (error) {
    if (error.name === 'AbortError') return;
    $('#task-list').replaceChildren();
    $('#error-message').textContent = error.message;
    $('#error-state').hidden = false;
    $('#empty-state').hidden = true;
    $('#pagination').hidden = true;
    $('#result-summary').textContent = '加载失败';
  } finally {
    if (activeRequest === request) setLoading(false);
  }
}

function setLoading(loading) {
  const body = $('#task-list');
  document.body.setAttribute('aria-busy', String(loading));
  if (loading) {
    const row = document.createElement('tr');
    row.className = 'loading-row';
    const cell = document.createElement('td');
    cell.colSpan = 9;
    cell.textContent = '正在读取任务列表...';
    row.append(cell);
    body.replaceChildren(row);
  }
}

function renderResult(result) {
  renderRows(result.items);
  renderSorting(result.sort_by, result.sort_order);
  renderPagination(result.pagination);
  const { page, page_size: pageSize, total_items: totalItems } = result.pagination;
  const start = totalItems ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, totalItems);
  $('#list-range').textContent = totalItems ? `显示 ${start}-${end}，共 ${formatNumber(totalItems)} 条任务` : '共 0 条任务';
  $('#result-summary').textContent = `共 ${formatNumber(totalItems)} 条任务`;
  $('#empty-state').hidden = totalItems !== 0;
}

function renderRows(items) {
  const rows = items.map((item) => {
    const row = document.createElement('tr');
    row.dataset.taskId = item.task_id;
    row.append(
      textCell(item.project_id),
      reportCell(item),
      textCell(item.copy_from_version),
      badgeCell(stateBadge(item.state)),
      badgeCell(typeBadge(item.task_type)),
      numericCell(item.score, 'score'),
      criticalIssueCell(item),
      numericCell(item.issue_count),
      textCell(formatDateTime(item.create_time)),
    );
    return row;
  });
  $('#task-list').replaceChildren(...rows);
}

function textCell(value) {
  const cell = document.createElement('td');
  cell.textContent = value || '--';
  cell.title = value || '';
  return cell;
}

function reportCell(item) {
  const cell = document.createElement('td');
  const link = document.createElement('a');
  link.className = 'report-link';
  link.href = item.report_url;
  link.textContent = item.review_version || '--';
  link.title = `查看 ${item.project_id} 的审核报告`;
  cell.append(link);
  return cell;
}

function numericCell(value, childClass = '') {
  const cell = document.createElement('td');
  cell.className = 'numeric';
  const content = document.createElement(childClass ? 'strong' : 'span');
  if (childClass) content.className = childClass;
  content.textContent = formatNumber(value);
  cell.append(content);
  return cell;
}

function criticalIssueCell(item) {
  const cell = numericCell(item.critical_issue_count);
  if (item.highest_severity != null && item.critical_issue_count > 0) {
    const detail = document.createElement('span');
    detail.className = 'severity-detail';
    detail.textContent = `等级 ${item.highest_severity}`;
    cell.append(detail);
  }
  return cell;
}

function badgeCell(badge) {
  const cell = document.createElement('td');
  cell.append(badge);
  return cell;
}

function stateBadge(state) {
  const states = {
    0: ['待审核', 'pending'], 1: ['审核中', 'running'], 2: ['已完成', 'completed'],
    3: ['部分完成或失败', 'partial'], 4: ['正在准备', 'preparing'],
  };
  const [label, className] = states[state] || [`状态 ${state}`, 'pending'];
  const badge = document.createElement('span');
  badge.className = `status-badge status-${className}`;
  badge.textContent = label;
  return badge;
}

function typeBadge(type) {
  const types = { 1: ['增量审核', 'incremental'], 2: ['全量审核', 'full'] };
  const [label, className] = types[type] || [`类型 ${type}`, 'full'];
  const badge = document.createElement('span');
  badge.className = `type-badge type-${className}`;
  badge.textContent = label;
  return badge;
}

function renderSorting(sortBy, sortOrder) {
  document.querySelectorAll('th[data-column]').forEach((header) => {
    const active = header.dataset.column === sortBy;
    header.setAttribute('aria-sort', active ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none');
    const indicator = header.querySelector('.sort-indicator');
    indicator.textContent = active ? (sortOrder === 'asc' ? '↑' : '↓') : '';
  });
}

function renderPagination(pagination) {
  const nav = $('#pagination');
  const { page, total_pages: totalPages } = pagination;
  nav.hidden = totalPages <= 1;
  if (totalPages <= 1) {
    nav.replaceChildren();
    return;
  }
  const children = [pageButton('上一页', page - 1, page === 1)];
  pageWindow(page, totalPages).forEach((value) => {
    if (value === 'ellipsis') {
      const span = document.createElement('span'); span.textContent = '...'; span.className = 'page-summary'; children.push(span);
    } else {
      children.push(pageButton(String(value), value, false, value === page));
    }
  });
  const summary = document.createElement('span');
  summary.className = 'page-summary';
  summary.textContent = `第 ${page} / ${totalPages} 页`;
  children.push(summary, pageButton('下一页', page + 1, page === totalPages));
  nav.replaceChildren(...children);
}

function pageWindow(page, totalPages) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const values = new Set([1, totalPages, page - 1, page, page + 1]);
  const pages = [...values].filter((value) => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  const result = [];
  pages.forEach((value, index) => {
    if (index && value - pages[index - 1] > 1) result.push('ellipsis');
    result.push(value);
  });
  return result;
}

function pageButton(label, page, disabled, active = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.dataset.page = String(page);
  button.disabled = disabled;
  button.classList.toggle('active', active);
  if (active) button.setAttribute('aria-current', 'page');
  return button;
}

$('#filter-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const dateFrom = $('#date-from-filter').value;
  const dateTo = $('#date-to-filter').value;
  const dateToInput = $('#date-to-filter');
  dateToInput.setCustomValidity(dateFrom && dateTo && dateFrom > dateTo ? '结束日期不能早于开始日期' : '');
  if (!dateToInput.reportValidity()) return;
  viewState.projectId = $('#project-filter').value.trim();
  viewState.reviewVersion = $('#version-filter').value.trim();
  viewState.dateFrom = dateFrom;
  viewState.dateTo = dateTo;
  viewState.taskType = $('#type-filter').value;
  viewState.taskState = $('#state-filter').value;
  viewState.page = 1;
  loadTasks({ historyMode: 'push' });
});

$('#reset-filters').addEventListener('click', () => {
  viewState = defaultState();
  syncForm();
  loadTasks({ historyMode: 'push' });
});

document.querySelectorAll('.sort-button').forEach((button) => {
  button.addEventListener('click', () => {
    const field = button.dataset.sort;
    if (viewState.sortBy === field) {
      viewState.sortOrder = viewState.sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      viewState.sortBy = field;
      viewState.sortOrder = DESCENDING_FIRST.has(field) ? 'desc' : 'asc';
    }
    viewState.page = 1;
    loadTasks({ historyMode: 'push' });
  });
});

$('#pagination').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-page]');
  if (!button || button.disabled) return;
  viewState.page = Number(button.dataset.page);
  loadTasks({ historyMode: 'push' });
  $('#task-list-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

$('#retry-load').addEventListener('click', () => loadTasks({ historyMode: 'none' }));
window.addEventListener('popstate', () => {
  readStateFromUrl();
  syncForm();
  loadTasks({ historyMode: 'none' });
});

readStateFromUrl();
syncForm();
loadTasks();
