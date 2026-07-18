const state = { page: 1, pageSize: 20, loading: false, rejectTarget: null };
const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;
let toastTimer;

function parameters() {
  const params = new URLSearchParams(location.search);
  params.set('page', state.page); params.set('page_size', state.pageSize); return params;
}
async function loadReport({ silent = false } = {}) {
  if (state.loading) return; state.loading = true; if (!silent) $('#loading').hidden = false; $('#error-state').hidden = true;
  try {
    const authorName = decodeURIComponent(location.pathname.split('/')[2] || '');
    const response = await fetch(`/api/authors/${encodeURIComponent(authorName)}/issue-report?${parameters()}`, { cache: 'no-store' });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.error?.message || body.detail?.[0]?.msg || `HTTP ${response.status}`); }
    render(await response.json());
  } catch (error) { $('#error-message').textContent = error.message; $('#error-state').hidden = false; }
  finally { state.loading = false; if (!silent) $('#loading').hidden = true; }
}
function render(report) {
  state.page = report.pagination.page; $('#page-title').textContent = `${report.author_name}的问题反馈`;
  const typeName = report.task_type === 2 ? '正式版' : '全量审核';
  $('#scope-label').textContent = `${report.author_name} · ${typeName}${report.start_date || report.end_date ? ` · ${report.start_date || '最早'} 至 ${report.end_date || '今天'}` : ''}`;
  const s = report.summary; const values = [
    ['严重问题数', number(s.severe_issue_count)], ['全部问题数', number(s.issue_count)], ['严重问题反馈比例', percent(s.severe_feedback_rate)],
    ['严重问题赞成比例', percent(s.severe_agree_rate)], ['全部问题反馈比例', percent(s.issue_feedback_rate)], ['文件总数', number(s.file_count)],
  ];
  $('#summary-grid').replaceChildren(...values.map(([label, value]) => { const box = document.createElement('div'); box.className = 'summary-item'; const name = document.createElement('span'); name.textContent = label; const count = document.createElement('strong'); count.textContent = value; box.append(name, count); return box; }));
  const start = report.pagination.total_items ? (report.pagination.page - 1) * report.pagination.page_size : 0;
  $('#issue-list').replaceChildren(...report.items.map((item, index) => issueRow(item, start + index + 1)));
  $('#empty-state').hidden = report.items.length > 0;
  const end = Math.min(start + report.items.length, report.pagination.total_items); $('#list-range').textContent = report.pagination.total_items ? `${start + 1}-${end} / ${report.pagination.total_items}` : '0 条问题';
  renderPagination(report.pagination);
}
function issueRow(item, no) {
  const row = document.createElement('tr');
  [no, item.file_name].forEach((value) => { const td = document.createElement('td'); td.textContent = value; row.append(td); });
  const severity = document.createElement('td'); const badge = document.createElement('span'); badge.className = `severity severity-${item.severity}`; badge.textContent = item.severity; severity.append(badge); row.append(severity);
  const codeCell = document.createElement('td'); const codeButton = document.createElement('button'); codeButton.type = 'button'; codeButton.className = 'code-trigger'; codeButton.textContent = `查看代码${item.issue_line_numbers ? ` · ${item.issue_line_numbers}行` : ''}`; codeButton.addEventListener('mouseenter', () => showCode(codeButton, item.contents)); codeButton.addEventListener('mouseleave', hideCode); codeButton.addEventListener('focus', () => showCode(codeButton, item.contents)); codeButton.addEventListener('blur', hideCode); codeCell.append(codeButton); row.append(codeCell);
  [item.description, item.suggestion].forEach((value) => { const td = document.createElement('td'); td.textContent = value || '--'; row.append(td); });
  const feedback = document.createElement('td'); feedback.append(feedbackActions(item)); row.append(feedback); return row;
}
function feedbackActions(item) {
  const actions = document.createElement('div'); actions.className = 'feedback-actions'; actions.dataset.fileId = item.file_id; actions.dataset.blockId = item.block_id; actions.dataset.issueId = item.issue_id;
  const agree = feedbackButton('agree', '赞成该问题', '👍', item.feedback_type === 'agree'); const reject = feedbackButton('reject', '反对该问题', '👎', item.feedback_type === 'reject');
  agree.addEventListener('click', () => saveFeedback(item, 'agree', '', actions)); reject.addEventListener('click', () => openReject(item, actions)); actions.append(agree, reject); return actions;
}
function feedbackButton(type, title, icon, active) { const button = document.createElement('button'); button.type = 'button'; button.className = `feedback-button ${type}${active ? ' active' : ''}`; button.title = title; button.setAttribute('aria-label', title); button.textContent = icon; return button; }
function openReject(item, actions) { state.rejectTarget = { item, actions }; $('#reject-reason').value = item.feedback_content || ''; $('#reject-dialog').showModal(); $('#reject-reason').focus(); }
async function saveFeedback(item, type, content, actions) {
  [...actions.querySelectorAll('button')].forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(`/api/feedback/${encodeURIComponent(item.file_id)}/${item.block_id}/${item.issue_id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feedback_type: type, feedback_content: content }) });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.error?.message || body.detail?.[0]?.msg || `HTTP ${response.status}`); }
    showToast(type === 'agree' ? '已记录赞成反馈' : '已记录反对反馈'); await loadReport({ silent: true });
  } catch (error) { showToast(`反馈保存失败：${error.message}`); }
  finally { [...actions.querySelectorAll('button')].forEach((button) => { button.disabled = false; }); }
}
function showCode(target, contents) { const popover = $('#code-popover'); $('#code-preview').textContent = (contents || []).join('\n') || '无代码内容'; popover.hidden = false; const rect = target.getBoundingClientRect(); const width = Math.min(780, window.innerWidth - 24); let left = Math.min(rect.left, window.innerWidth - width - 12); left = Math.max(12, left); const top = rect.bottom + 8 + Math.min(540, window.innerHeight - 24) > window.innerHeight ? Math.max(12, rect.top - Math.min(540, window.innerHeight - 24) - 8) : rect.bottom + 8; popover.style.left = `${left}px`; popover.style.top = `${top}px`; }
function hideCode() { $('#code-popover').hidden = true; }
function renderPagination(p) { const container = $('#pagination'); container.hidden = p.total_pages <= 1; if (p.total_pages <= 1) { container.replaceChildren(); return; } const buttons = [pageButton('上一页', p.page - 1, p.page === 1)]; for (let page = Math.max(1, p.page - 2); page <= Math.min(p.total_pages, p.page + 2); page += 1) buttons.push(pageButton(String(page), page, false, page === p.page)); buttons.push(pageButton('下一页', p.page + 1, p.page === p.total_pages)); container.replaceChildren(...buttons); }
function pageButton(label, page, disabled, active = false) { const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.disabled = disabled; button.classList.toggle('active', active); button.addEventListener('click', () => { state.page = page; loadReport(); }); return button; }
function showToast(message) { const toast = $('#toast'); toast.textContent = message; toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 2600); }
$('#retry-load').addEventListener('click', loadReport); $('#reject-cancel').addEventListener('click', () => $('#reject-dialog').close()); $('#reject-close').addEventListener('click', () => $('#reject-dialog').close()); $('#reject-form').addEventListener('submit', async (event) => { event.preventDefault(); const reason = $('#reject-reason').value.trim(); if (!reason) { $('#reject-reason').reportValidity(); return; } const target = state.rejectTarget; $('#reject-dialog').close(); if (target) await saveFeedback(target.item, 'reject', reason, target.actions); });
state.page = Math.max(1, Number(new URLSearchParams(location.search).get('page') || 1)); loadReport();
