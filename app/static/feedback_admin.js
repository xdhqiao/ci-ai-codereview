const state = { page: 1, pageSize: 20, loading: false };
const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const percent = (value) => `${Number(value || 0).toFixed(1)}%`;
const dateTime = (value) => value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '--';

function initialize() {
  const params = new URLSearchParams(window.location.search);
  $('#start-date').value = params.get('start_date') || '';
  $('#end-date').value = params.get('end_date') || '';
  $('#view-filter').value = params.get('view') || 'prd_version';
  state.page = Math.max(1, Number(params.get('page') || 1));
  loadReport();
}

async function loadReport() {
  if (state.loading) return;
  state.loading = true; $('#loading').hidden = false; $('#error-state').hidden = true;
  const params = new URLSearchParams({ view: $('#view-filter').value, page: state.page, page_size: state.pageSize });
  if ($('#start-date').value) params.set('start_date', $('#start-date').value);
  if ($('#end-date').value) params.set('end_date', $('#end-date').value);
  history.replaceState(null, '', `${location.pathname}?${params}`);
  try {
    const response = await fetch(`/api/admin/feedback?${params}`, { cache: 'no-store' });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.error?.message || `HTTP ${response.status}`); }
    render(await response.json());
  } catch (error) {
    $('#error-message').textContent = error.message; $('#error-state').hidden = false;
    $('#list-body').replaceChildren(); $('#empty-state').hidden = true;
  } finally { state.loading = false; $('#loading').hidden = true; }
}

function render(report) {
  state.page = report.pagination.page;
  const labels = { prd_version: '正式版', full_scan: '全量审核', author_prd: '维护人（正式版）', author_full: '维护人（全量审核）' };
  $('#scope-label').textContent = labels[report.view];
  const summary = report.summary;
  const values = [
    ['项目 ID', number(summary.project_count)], ['版本', number(summary.version_count)],
    ['维护人', number(summary.author_count)], ['严重问题', number(summary.severe_issue_count)],
    ['严重问题反馈率', percent(summary.severe_feedback_rate)], ['全部问题反馈率', percent(summary.issue_feedback_rate)],
  ];
  $('#summary-grid').replaceChildren(...values.map(([label, value]) => {
    const box = document.createElement('div'); box.className = 'summary-item';
    const name = document.createElement('span'); name.textContent = label;
    const count = document.createElement('strong'); count.textContent = value; box.append(name, count); return box;
  }));
  drawPie($('#feedback-pie'), [
    { label: '赞成', value: summary.severe_agree_count, color: '#087f5b' },
    { label: '反对', value: summary.severe_reject_count, color: '#c92a2a' },
  ], $('#feedback-legend'));
  const severityColors = { 5: '#c92a2a', 4: '#e8590c', 3: '#e0a800', 2: '#1971c2', 1: '#6c757d' };
  drawPie($('#severity-pie'), [5, 4, 3, 2, 1].map((level) => ({ label: `等级 ${level}`, value: summary.severity_distribution[String(level)] || 0, color: severityColors[level] })), $('#severity-legend'));
  renderTable(report); renderPagination(report.pagination);
}

function drawPie(canvas, segments, legend) {
  const ratio = window.devicePixelRatio || 1; const width = 320; const height = 230;
  canvas.width = width * ratio; canvas.height = height * ratio; const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height); const total = segments.reduce((sum, item) => sum + item.value, 0);
  let angle = -Math.PI / 2;
  if (!total) { ctx.beginPath(); ctx.arc(160, 115, 78, 0, Math.PI * 2); ctx.fillStyle = '#e8edec'; ctx.fill(); }
  segments.forEach((item) => { if (!item.value || !total) return; const next = angle + Math.PI * 2 * item.value / total; ctx.beginPath(); ctx.moveTo(160, 115); ctx.arc(160, 115, 78, angle, next); ctx.closePath(); ctx.fillStyle = item.color; ctx.fill(); angle = next; });
  ctx.beginPath(); ctx.arc(160, 115, 42, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
  ctx.fillStyle = '#172126'; ctx.font = '700 18px "Segoe UI"'; ctx.textAlign = 'center'; ctx.fillText(number(total), 160, 120);
  legend.replaceChildren(...segments.map((item) => { const row = document.createElement('div'); row.className = 'legend-item'; const swatch = document.createElement('span'); swatch.className = 'legend-swatch'; swatch.style.background = item.color; const label = document.createElement('span'); label.textContent = item.label; const value = document.createElement('strong'); value.textContent = total ? `${number(item.value)} · ${percent(item.value * 100 / total)}` : '0 · 0.0%'; row.append(swatch, label, value); return row; }));
}

function renderTable(report) {
  const taskMode = ['prd_version', 'full_scan'].includes(report.view);
  const headers = taskMode
    ? ['项目', '版本', '严重问题数', '严重问题反馈比例', '严重问题赞成比例', '问题总数', '问题反馈比例', '任务创建时间']
    : ['维护人', '严重问题数', '严重问题反馈比例', '严重问题赞成比例', '全部问题数', '全部问题反馈比例'];
  const numericColumns = taskMode ? [2, 3, 4, 5, 6] : [1, 2, 3, 4, 5];
  $('#list-head').replaceChildren(...headers.map((value, index) => { const th = document.createElement('th'); th.textContent = value; th.classList.toggle('numeric', numericColumns.includes(index)); return th; }));
  const items = taskMode ? report.task_items : report.author_items;
  $('#list-body').replaceChildren(...items.map((item) => taskMode ? taskRow(item) : authorRow(item)));
  $('#empty-state').hidden = items.length > 0;
  const p = report.pagination; const start = p.total_items ? (p.page - 1) * p.page_size + 1 : 0; const end = Math.min(p.page * p.page_size, p.total_items);
  $('#list-range').textContent = p.total_items ? `${start}-${end} / ${p.total_items}` : '0 条记录';
}

function taskRow(item) {
  const row = document.createElement('tr');
  const values = [item.project_id, item.review_version, item.severe_issue_count, percent(item.severe_feedback_rate), percent(item.severe_agree_rate), item.issue_count, percent(item.issue_feedback_rate), dateTime(item.create_time)];
  values.forEach((value, index) => { const td = document.createElement('td'); if (index === 1) { const link = document.createElement('a'); link.href = item.report_url; link.textContent = value; td.append(link); } else td.textContent = value; if ([2, 3, 4, 5, 6].includes(index)) td.className = 'numeric'; row.append(td); }); return row;
}
function authorRow(item) {
  const row = document.createElement('tr'); const values = [item.author_name, item.severe_issue_count, percent(item.severe_feedback_rate), percent(item.severe_agree_rate), item.issue_count, percent(item.issue_feedback_rate)];
  values.forEach((value, index) => { const td = document.createElement('td'); if (index === 0) { const link = document.createElement('a'); link.href = item.report_url; link.textContent = value; link.title = item.file_author; td.append(link); } else { td.textContent = value; td.className = 'numeric'; } row.append(td); }); return row;
}

function renderPagination(pagination) {
  const container = $('#pagination'); container.hidden = pagination.total_pages <= 1;
  if (pagination.total_pages <= 1) { container.replaceChildren(); return; }
  const buttons = [pageButton('上一页', pagination.page - 1, pagination.page === 1)];
  for (let page = Math.max(1, pagination.page - 2); page <= Math.min(pagination.total_pages, pagination.page + 2); page += 1) buttons.push(pageButton(String(page), page, false, page === pagination.page));
  buttons.push(pageButton('下一页', pagination.page + 1, pagination.page === pagination.total_pages)); container.replaceChildren(...buttons);
}
function pageButton(label, page, disabled, active = false) { const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.disabled = disabled; button.classList.toggle('active', active); button.addEventListener('click', () => { state.page = page; loadReport(); }); return button; }

$('#filter-form').addEventListener('submit', (event) => { event.preventDefault(); state.page = 1; loadReport(); });
$('#reset-filter').addEventListener('click', () => { $('#start-date').value = ''; $('#end-date').value = ''; $('#view-filter').value = 'prd_version'; state.page = 1; loadReport(); });
$('#retry-load').addEventListener('click', loadReport);
initialize();
