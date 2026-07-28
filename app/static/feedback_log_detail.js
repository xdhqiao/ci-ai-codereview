const $ = (selector) => document.querySelector(selector);
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);

async function loadDetail() {
  const query = new URLSearchParams(window.location.search);
  const required = ['project_id', 'review_version', 'copy_from_version'];
  const missing = required.filter((key) => !query.get(key));
  if (missing.length) {
    showError(`缺少参数：${missing.join(', ')}`);
    return;
  }
  const apiParams = new URLSearchParams();
  [...required, 'start_date', 'end_date'].forEach((key) => {
    if (query.get(key)) apiParams.set(key, query.get(key));
  });
  try {
    const response = await fetch(`/api/admin/feedback-logs/detail?${apiParams}`, { cache: 'no-store' });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || `HTTP ${response.status}`);
    }
    renderDetail(await response.json());
  } catch (error) {
    showError(error.message);
  } finally {
    $('#loading').hidden = true;
  }
}

function renderDetail(report) {
  $('#version-title').textContent = `${report.project_id} · ${report.review_version} vs ${report.copy_from_version}`;
  $('#scope-label').textContent = `${report.start_date} 至 ${report.end_date}`;
  const summary = report.summary;
  $('#detail-summary').replaceChildren(
    summaryItem(`反馈 ${number(summary.feedback_count)}`),
    summaryItem(`赞同 ${percent(summary.agree_rate)}`),
    summaryItem(`严重问题 ${number(summary.severe_feedback_count)}`),
    summaryItem(`严重问题赞同 ${percent(summary.severe_agree_rate)}`),
  );
  $('#detail-body').replaceChildren(...report.items.map((item, index) => detailRow(item, index + 1)));
  $('#list-range').textContent = `共 ${report.items.length} 条`;
  $('#empty-state').hidden = report.items.length > 0;

  const back = new URLSearchParams({
    start_date: report.start_date,
    end_date: report.end_date,
    group_by: 'version',
    page: '1',
  });
  $('#back-link').href = `/admin/feedback-logs.html?${back}`;
}

function summaryItem(text) {
  const item = document.createElement('span');
  item.textContent = text;
  return item;
}

function detailRow(item, no) {
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
  appendCell(row, item.severity);
  appendCell(row, item.feedback_content || '—', 'wrap-cell');
  appendCell(row, item.description, 'wrap-cell');
  appendCell(row, item.suggestion, 'wrap-cell');
  return row;
}

function appendCell(row, value, className = '') {
  const cell = document.createElement('td');
  cell.textContent = String(value ?? '');
  if (className) cell.className = className;
  row.append(cell);
}

function showError(message) {
  $('#error-message').textContent = message;
  $('#error-state').hidden = false;
  $('#loading').hidden = true;
}

loadDetail();
