const state = { page: 1, pageSize: 20, loading: false };
const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;
const query = new URLSearchParams(window.location.search);

function requestParams() {
  const params = new URLSearchParams({
    file_author: query.get('file_author') || '',
    page: String(state.page),
    page_size: String(state.pageSize),
  });
  if (query.get('start_date')) params.set('start_date', query.get('start_date'));
  if (query.get('end_date')) params.set('end_date', query.get('end_date'));
  return params;
}

async function loadDetail() {
  if (state.loading) return;
  if (!query.get('file_author')) {
    showError('缺少参数：file_author');
    return;
  }
  state.loading = true;
  $('#loading').hidden = false;
  $('#error-state').hidden = true;
  try {
    const params = requestParams();
    const response = await fetch(`/api/admin/feedback-logs/author-detail?${params}`, { cache: 'no-store' });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || `HTTP ${response.status}`);
    }
    const report = await response.json();
    state.page = report.pagination.page;
    renderDetail(report);
    const pageParams = new URLSearchParams({
      file_author: query.get('file_author'),
      start_date: report.start_date,
      end_date: report.end_date,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    window.history.replaceState({}, '', `/admin/feedback-log-author-detail.html?${pageParams}`);
  } catch (error) {
    showError(error.message);
  } finally {
    state.loading = false;
    $('#loading').hidden = true;
  }
}

function renderDetail(report) {
  $('#page-title').textContent = `${report.author_name}的反馈日志`;
  $('#scope-label').textContent = `${report.start_date} 至 ${report.end_date}`;
  const summary = report.summary;
  const metrics = [
    ['反馈总数', number(summary.feedback_count)],
    ['全部反馈赞同百分比', percent(summary.agree_rate)],
    ['严重问题总数', number(summary.severe_feedback_count)],
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

  const offset = (report.pagination.page - 1) * report.pagination.page_size;
  $('#detail-body').replaceChildren(
    ...report.items.map((item, index) => detailRow(item, offset + index + 1)),
  );
  $('#empty-state').hidden = report.items.length > 0;
  const start = report.pagination.total_items ? offset + 1 : 0;
  const end = Math.min(offset + report.items.length, report.pagination.total_items);
  $('#list-range').textContent = `${start}-${end} / ${report.pagination.total_items}`;
  renderPagination(report.pagination);

  const back = new URLSearchParams({
    start_date: report.start_date,
    end_date: report.end_date,
    group_by: 'author',
    page: '1',
  });
  $('#back-link').href = `/admin/feedback-logs.html?${back}`;
}

function detailRow(item, no) {
  const row = document.createElement('tr');
  appendCell(row, no);
  appendCell(row, item.project_id);
  appendCell(row, item.review_version);
  appendCell(row, item.copy_from_version);
  appendCell(row, item.file_name);
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
    loadDetail();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  return button;
}

function showError(message) {
  $('#error-message').textContent = message;
  $('#error-state').hidden = false;
  $('#loading').hidden = true;
}

$('#retry-load').addEventListener('click', loadDetail);
state.page = Math.max(1, Number(query.get('page') || 1));
loadDetail();
