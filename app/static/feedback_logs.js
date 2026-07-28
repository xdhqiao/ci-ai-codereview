const state = { page: 1, pageSize: 20, groupBy: 'none', loading: false };
const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;

function dateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function recentMonth() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 29);
  return { start: dateValue(start), end: dateValue(end) };
}

function initializeFilters() {
  const query = new URLSearchParams(window.location.search);
  const defaults = recentMonth();
  $('#start-date').value = query.get('start_date') || defaults.start;
  $('#end-date').value = query.get('end_date') || defaults.end;
  state.groupBy = ['none', 'version', 'author'].includes(query.get('group_by'))
    ? query.get('group_by')
    : 'none';
  state.page = Math.max(1, Number(query.get('page') || 1));
  $('#group-by').value = state.groupBy;
}

async function loadReport() {
  if (state.loading) return;
  state.loading = true;
  $('#loading').hidden = false;
  $('#error-state').hidden = true;
  try {
    const params = new URLSearchParams({
      start_date: $('#start-date').value,
      end_date: $('#end-date').value,
      group_by: state.groupBy,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    const response = await fetch(`/api/admin/feedback-logs?${params}`, { cache: 'no-store' });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || `HTTP ${response.status}`);
    }
    const report = await response.json();
    state.page = report.pagination.page;
    renderReport(report);
    window.history.replaceState({}, '', `/admin/feedback-logs.html?${params}`);
  } catch (error) {
    $('#error-message').textContent = error.message;
    $('#error-state').hidden = false;
  } finally {
    state.loading = false;
    $('#loading').hidden = true;
  }
}

function renderReport(report) {
  $('#scope-label').textContent = `${report.start_date} 至 ${report.end_date}`;
  const summary = report.summary;
  const metrics = [
    ['反馈总数', number(summary.feedback_count)],
    ['全部反馈赞同百分比', percent(summary.agree_rate)],
    ['严重问题反馈总数', number(summary.severe_feedback_count)],
    ['严重问题赞同百分比', percent(summary.severe_agree_rate)],
  ];
  $('#summary-grid').replaceChildren(...metrics.map(([label, value]) => {
    const card = document.createElement('article');
    card.className = 'metric';
    const caption = document.createElement('span');
    caption.textContent = label;
    const strong = document.createElement('strong');
    strong.textContent = value;
    card.append(caption, strong);
    return card;
  }));

  renderTable(report);
  renderPagination(report.pagination);
}

function renderTable(report) {
  const definitions = {
    none: {
      headers: ['NO', '文件名', '反馈者', '赞成/反对', '反馈信息', '问题描述', '修复建议', '时间'],
      items: report.log_items,
      row: logRow,
    },
    version: {
      headers: ['NO', '项目ID', '当前版本', '对比版本', '问题总数', '赞成比例', '严重问题总数', '严重问题赞成比例'],
      items: report.version_items,
      row: versionRow,
    },
    author: {
      headers: ['NO', '负责人（反馈者）', '反馈的问题总数', '赞成比例'],
      items: report.author_items,
      row: authorRow,
    },
  };
  const definition = definitions[report.group_by];
  $('#list-head').replaceChildren(...definition.headers.map((text) => {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = text;
    return th;
  }));
  const offset = (report.pagination.page - 1) * report.pagination.page_size;
  $('#list-body').replaceChildren(...definition.items.map((item, index) => definition.row(item, offset + index + 1)));
  $('#empty-state').hidden = definition.items.length > 0;
  const start = report.pagination.total_items ? offset + 1 : 0;
  const end = Math.min(offset + definition.items.length, report.pagination.total_items);
  $('#list-range').textContent = `${start}-${end} / ${report.pagination.total_items}`;
}

function logRow(item, no) {
  const row = document.createElement('tr');
  appendCell(row, no);
  appendCell(row, item.file_name);
  appendCell(row, item.author_name);
  const feedback = document.createElement('td');
  const badge = document.createElement('span');
  badge.className = `feedback-badge ${item.feedback_type}`;
  badge.textContent = item.feedback_type === 'agree' ? '赞同' : '反对';
  feedback.append(badge);
  row.append(feedback);
  appendCell(row, item.feedback_content || '—', 'wrap-cell');
  appendCell(row, item.description, 'wrap-cell');
  appendCell(row, item.suggestion, 'wrap-cell');
  appendCell(row, formatDateTime(item.create_time));
  return row;
}

function versionRow(item, no) {
  const row = document.createElement('tr');
  appendCell(row, no);
  appendCell(row, item.project_id);
  const version = document.createElement('td');
  const link = document.createElement('a');
  link.href = item.detail_url;
  link.textContent = item.review_version;
  version.append(link);
  row.append(version);
  appendCell(row, item.copy_from_version);
  appendCell(row, number(item.issue_count));
  appendCell(row, percent(item.agree_rate));
  appendCell(row, number(item.severe_issue_count));
  appendCell(row, percent(item.severe_agree_rate));
  return row;
}

function authorRow(item, no) {
  const row = document.createElement('tr');
  appendCell(row, no);
  const author = document.createElement('td');
  const link = document.createElement('a');
  link.href = item.detail_url;
  link.textContent = item.author_name;
  author.append(link);
  row.append(author);
  appendCell(row, number(item.issue_count));
  appendCell(row, percent(item.agree_rate));
  return row;
}

function appendCell(row, value, className = '') {
  const cell = document.createElement('td');
  cell.textContent = String(value ?? '');
  if (className) cell.className = className;
  row.append(cell);
}

function formatDateTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(value));
}

function renderPagination(pagination) {
  const nav = $('#pagination');
  nav.replaceChildren();
  nav.hidden = pagination.total_pages <= 1;
  if (pagination.total_pages <= 1) return;
  nav.append(pageButton('上一页', pagination.page - 1, pagination.page === 1));
  const first = Math.max(1, pagination.page - 3);
  const last = Math.min(pagination.total_pages, pagination.page + 3);
  for (let page = first; page <= last; page += 1) {
    const button = pageButton(String(page), page, false);
    if (page === pagination.page) button.classList.add('active');
    nav.append(button);
  }
  nav.append(pageButton('下一页', pagination.page + 1, pagination.page === pagination.total_pages));
}

function pageButton(label, page, disabled) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener('click', () => {
    state.page = page;
    loadReport();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  return button;
}

function applyFilters() {
  state.groupBy = $('#group-by').value;
  state.page = 1;
  loadReport();
}

$('#filter-form').addEventListener('submit', (event) => {
  event.preventDefault();
  applyFilters();
});
$('#apply-filter').addEventListener('click', applyFilters);
$('#reset-filter').addEventListener('click', () => {
  const defaults = recentMonth();
  $('#start-date').value = defaults.start;
  $('#end-date').value = defaults.end;
  $('#group-by').value = 'none';
  state.groupBy = 'none';
  state.page = 1;
  loadReport();
});
$('#retry-load').addEventListener('click', loadReport);

initializeFilters();
loadReport();
