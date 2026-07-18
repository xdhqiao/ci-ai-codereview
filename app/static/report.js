const state = {
  reportEndpoint: `/api/reports${window.location.pathname}`,
  triggerRevision: new URLSearchParams(window.location.search).get('trigger_revision') || '',
  author: '',
  page: 1,
  pageSize: 300,
  rejectTarget: null,
  scoreDimensions: null,
  taskId: '',
  loading: false,
  refreshTimer: null,
};

const labels = {
  logic_score: '逻辑正确性',
  performance_score: '性能',
  security_score: '安全性',
  readable_score: '可读性',
  code_style_score: '代码规范',
};

const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const duration = (milliseconds) => {
  const seconds = Math.max(0, Math.round((milliseconds || 0) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return [hours ? `${hours} 小时` : '', minutes ? `${minutes} 分` : '', `${rest} 秒`].filter(Boolean).join(' ');
};
const dateTime = (value) => value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(value)) : '--';

async function loadReport({ silent = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!silent) $('#loading').hidden = false;
  $('#error-state').hidden = true;
  const params = new URLSearchParams({ page: state.page, page_size: state.pageSize });
  if (state.author) params.set('author', state.author);
  if (state.triggerRevision) params.set('trigger_revision', state.triggerRevision);
  try {
    const response = await fetch(`${state.reportEndpoint}?${params}`, { cache: 'no-store' });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${response.status}`);
    }
    const report = await response.json();
    state.taskId = report.overview.task_id;
    state.author = report.selected_author;
    state.page = report.pagination.page;
    renderReport(report);
    $('#report-root').hidden = false;
    scheduleRefresh(report);
  } catch (error) {
    if (silent && !$('#report-root').hidden) {
      showToast(`进度刷新失败：${error.message}`);
      clearTimeout(state.refreshTimer);
      state.refreshTimer = setTimeout(() => loadReport({ silent: true }), 5000);
    } else {
      $('#report-root').hidden = true;
      $('#error-message').textContent = error.message;
      $('#error-state').hidden = false;
    }
  } finally {
    if (!silent) $('#loading').hidden = true;
    state.loading = false;
  }
}

function renderReport(report) {
  renderOverview(report.overview, report.progress);
  renderProgress(report.progress, report.overview);
  renderScores(report.overview);
  renderMetrics(report.metrics);
  renderAuthors(report.authors, report.selected_author, report.author_name_map || {});
  renderCriticalIssues(report.critical_issues, report.highest_severity);
  renderFiles(report.files, report.pagination);
  renderPagination($('#pagination-top'), report.pagination);
  renderPagination($('#pagination-bottom'), report.pagination);
}

function scheduleRefresh(report) {
  clearTimeout(state.refreshTimer);
  const activeState = [0, 1, 4].includes(report.overview.state);
  const waitingForAutomaticRetry = Boolean(report.progress.next_retry_time);
  if (!activeState && !waitingForAutomaticRetry && !report.progress.retry_in_progress) return;
  const seconds = Math.max(2, report.progress.auto_refresh_seconds || 5);
  state.refreshTimer = setTimeout(() => loadReport({ silent: true }), seconds * 1000);
}

function renderOverview(overview, progress) {
  $('#project-title').textContent = overview.view_mode === 'snapshot'
    ? `${overview.project_id} 变更快照报告`
    : `${overview.project_id} 审核报告`;
  const status = $('#task-state');
  const statusNames = {
    pending: '等待审核', running: '审核中', completed: '审核完成', partial: '部分失败', failed: '审核失败',
    interrupted: '等待恢复', preparing: '正在准备', retry_pending: '续审排队中', retry_running: '失败项续审中',
  };
  const hasUnreviewedBlocks = progress.pending_block_num > 0 || progress.reviewing_block_num > 0;
  status.textContent = hasUnreviewedBlocks
    ? '审核中'
    : (statusNames[overview.completion_status] || overview.completion_status || `状态 ${overview.state}`);
  status.classList.toggle('partial', overview.state !== 2 || hasUnreviewedBlocks);
  status.classList.toggle('failed', ['partial', 'failed'].includes(overview.completion_status));
  const values = [
    ['审核项目', overview.project_id],
    ['审核版本', overview.review_version],
    ['参照版本', overview.review_mode === 'full' ? '全量审核，无参照版本' : overview.copy_from_version],
    ['审核时间', dateTime(overview.create_time)],
    ['审核时长', duration(overview.process_time_ms)],
  ];
  if (overview.view_mode === 'snapshot') {
    values.splice(
      3,
      0,
      ['快照 ID', overview.snapshot_id],
      ['提交轮次', `第 ${overview.trigger_revision} 次（当前最新第 ${overview.trigger_count} 次）`],
    );
    const removedFiles = overview.removed_file_names || [];
    if (removedFiles.length) {
      values.push(['删除文件', removedFiles.join('、')]);
    }
  }
  $('#overview-grid').replaceChildren(...values.map(([term, value]) => {
    const dl = document.createElement('dl');
    dl.className = 'datum';
    const dt = document.createElement('dt');
    dt.textContent = term;
    const dd = document.createElement('dd');
    dd.textContent = value || '--';
    dl.append(dt, dd);
    return dl;
  }));
}

function renderProgress(progress, overview) {
  $('#progress-percentage').textContent = `${progress.percentage}%`;
  $('#progress-fill').style.width = `${progress.percentage}%`;
  const track = $('.progress-track');
  track.setAttribute('aria-valuenow', String(progress.percentage));
  const values = [
    `文件：${number(progress.completed_file_num)} 完成 / ${number(progress.reviewing_file_num)} 审核中 / ${number(progress.pending_file_num)} 待处理 / ${number(progress.failed_file_num)} 失败`,
    `Block：${number(progress.completed_block_num)} 完成 / ${number(progress.reviewing_block_num)} 审核中 / ${number(progress.pending_block_num)} 待处理 / ${number(progress.failed_block_num)} 失败`,
  ];
  $('#progress-details').replaceChildren(...values.map((value) => {
    const span = document.createElement('span'); span.textContent = value; return span;
  }));

  const retryButton = $('#retry-failures-button');
  retryButton.hidden = false;
  retryButton.disabled = true;
  if (progress.retry_in_progress) {
    retryButton.textContent = '失败项重新审核中';
  } else if (progress.retry_available) {
    retryButton.disabled = false;
    retryButton.textContent = `重新审核失败项（${progress.retryable_block_num}）`;
  } else if (progress.percentage >= 100) {
    retryButton.textContent = '审核已完成';
  } else if (progress.pending_block_num > 0 || progress.reviewing_block_num > 0) {
    retryButton.textContent = '审核进行中';
  } else {
    retryButton.textContent = '暂无可重新审核项';
  }
  const retryStatus = $('#retry-status');
  const messages = [];
  if (progress.retry_in_progress) messages.push('人工续审已进入最高优先级队列，已完成 Block 会直接复用。');
  if (progress.pending_block_num > 0 || progress.reviewing_block_num > 0) {
    messages.push(`仍有 ${number(progress.pending_block_num)} 个待审、${number(progress.reviewing_block_num)} 个审核中 Block，完成后才能重新审核失败项。`);
  }
  if (progress.next_retry_time && overview.state === 3) messages.push(`自动重试时间：${dateTime(progress.next_retry_time)}`);
  if (progress.manual_retry_count) messages.push(`已人工续审 ${number(progress.manual_retry_count)} 次。`);
  retryStatus.textContent = messages.join(' ');
  retryStatus.hidden = messages.length === 0;
}

function renderScores(overview) {
  $('#overall-score').textContent = overview.overall_score;
  $('#change-summary').textContent = `变更 ${number(overview.changed_line_num)} 行，新增 ${number(overview.added_line_num)} 行`;
  const dimensions = Object.entries(labels).map(([key, label]) => ({ key, label, value: overview.scores[key] }));
  state.scoreDimensions = dimensions;
  $('#dimension-list').replaceChildren(...dimensions.map((item) => {
    const row = document.createElement('div');
    row.className = 'dimension-row';
    const label = document.createElement('span');
    label.textContent = item.label;
    const bar = document.createElement('div');
    bar.className = 'bar';
    const fill = document.createElement('span');
    fill.style.width = `${item.value}%`;
    bar.append(fill);
    const score = document.createElement('strong');
    score.textContent = item.value;
    row.append(label, bar, score);
    return row;
  }));
  drawRadar(dimensions);
}

function drawRadar(dimensions) {
  const canvas = $('#score-radar');
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 420;
  const height = 300;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  const center = { x: width / 2, y: height / 2 };
  const radius = Math.min(width * .31, 108);
  const point = (index, scale) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / dimensions.length;
    return { x: center.x + Math.cos(angle) * radius * scale, y: center.y + Math.sin(angle) * radius * scale };
  };
  ctx.strokeStyle = '#d2dadb';
  ctx.lineWidth = 1;
  for (let level = 1; level <= 5; level += 1) {
    ctx.beginPath();
    dimensions.forEach((_, index) => {
      const p = point(index, level / 5);
      index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
    });
    ctx.closePath();
    ctx.stroke();
  }
  dimensions.forEach((_, index) => {
    const p = point(index, 1);
    ctx.beginPath(); ctx.moveTo(center.x, center.y); ctx.lineTo(p.x, p.y); ctx.stroke();
  });
  ctx.beginPath();
  dimensions.forEach((item, index) => {
    const p = point(index, item.value / 100);
    index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
  });
  ctx.closePath();
  ctx.fillStyle = '#087f5b33';
  ctx.strokeStyle = '#087f5b';
  ctx.lineWidth = 2;
  ctx.fill(); ctx.stroke();
  ctx.font = '12px "Microsoft YaHei", sans-serif';
  ctx.fillStyle = '#526066';
  ctx.textAlign = 'center';
  dimensions.forEach((item, index) => {
    const p = point(index, 1.2);
    ctx.fillText(item.label, p.x, p.y + 4);
  });
}

function renderMetrics(metrics) {
  const values = [
    ['总 Token', number(metrics.total_tokens)], ['输入 Token', number(metrics.prompt_tokens)],
    ['输出 Token', number(metrics.completion_tokens)], ['LLM 耗时', duration(metrics.llm_elapsed_ms)],
    ['文件数', number(metrics.file_num)], ['已审核文件', number(metrics.reviewed_file_num)],
    ['代码块', number(metrics.code_block_num)], ['有效问题', number(metrics.issue_num)],
    ['已过滤问题', number(metrics.filtered_issue_num)], ['高危问题', number(metrics.critical_issue_num)],
    ['未完整文件', number(metrics.incomplete_file_num)], ['工具调用', number(metrics.tool_call_num)],
    ['模型轮次', number(metrics.model_round_num)], ['上下文压缩', number(metrics.memory_compression_num)],
  ];
  $('#metric-grid').replaceChildren(...values.map(([label, value]) => {
    const item = document.createElement('div');
    item.className = 'metric';
    const name = document.createElement('span'); name.textContent = label;
    const count = document.createElement('strong'); count.textContent = value;
    item.append(name, count);
    return item;
  }));
}

function renderAuthors(authors, selected, authorNameMap) {
  const control = $('#author-control');
  control.hidden = authors.length === 0;
  if (!authors.length) return;
  const select = $('#author-select');
  select.replaceChildren();
  const all = new Option('全部负责人', '');
  select.add(all);
  authors.forEach((author) => {
    const option = new Option(authorNameMap[author] || '未配置姓名', author);
    select.add(option);
  });
  select.value = selected;
}

function renderCriticalIssues(issues, highestSeverity) {
  const body = $('#critical-issues');
  body.replaceChildren(...issues.map((issue, index) => {
    const row = document.createElement('tr');
    const values = [index + 1, issue.file_name, issue.severity, issue.issue_line_numbers || '--', issue.type || '--', issue.description, issue.suggestion];
    values.forEach((value, valueIndex) => {
      const cell = document.createElement('td');
      if (valueIndex === 2) cell.append(severityBadge(value)); else cell.textContent = value;
      row.append(cell);
    });
    return row;
  }));
  $('#critical-empty').hidden = issues.length > 0;
  $('#critical-title').textContent = highestSeverity == null ? '严重问题' : `严重问题 · 等级 ${highestSeverity}`;
}

function renderFiles(files, pagination) {
  const start = pagination.total_items ? (pagination.page - 1) * pagination.page_size + 1 : 0;
  const end = Math.min(pagination.page * pagination.page_size, pagination.total_items);
  $('#file-range').textContent = pagination.total_items ? `${start}-${end} / ${pagination.total_items}` : '0 个文件';
  $('#file-list').replaceChildren(...files.map(renderFile));
}

function renderFile(file) {
  const section = document.createElement('article');
  section.className = 'file-review';
  const header = document.createElement('header');
  header.className = 'file-header';
  const title = document.createElement('div');
  title.className = 'file-title';
  const heading = document.createElement('h3'); heading.textContent = file.file_name;
  title.append(heading);
  title.append(reviewStatus(file.status));
  if (file.file_author) {
    const author = document.createElement('span'); author.className = 'file-author'; author.textContent = `负责人：${file.file_author_name || '未配置姓名'}`; title.append(author);
  }
  const dimensions = document.createElement('span');
  dimensions.className = 'file-dimensions';
  dimensions.textContent = Object.entries(labels).map(([key, label]) => `${label} ${file.scores[key]}`).join(' · ');
  title.append(dimensions);
  const score = document.createElement('span'); score.className = 'file-score'; score.textContent = '文件评分';
  const scoreValue = document.createElement('strong'); scoreValue.textContent = file.overall_score; score.append(scoreValue);
  header.append(title, score);
  section.append(header, ...file.blocks.map((block) => renderBlock(file, block)));
  return section;
}

function renderBlock(file, block) {
  const section = document.createElement('section'); section.className = 'block-review';
  const heading = document.createElement('div'); heading.className = 'block-heading';
  const name = document.createElement('strong'); name.textContent = `Block ${block.block_id}`;
  const stats = document.createElement('span'); stats.textContent = `评分 ${block.overall_score} · 变更 ${block.changed_line_num} 行 · 耗时 ${duration(block.process_time_ms)}`;
  heading.append(name, reviewStatus(block.status), stats);
  const code = document.createElement('div'); code.className = 'code-panel';
  const pre = document.createElement('pre');
  block.contents.forEach((line) => {
    const span = document.createElement('span'); span.className = 'code-line'; span.textContent = line;
    if (line.length > 6 && line[6] === '+') span.classList.add('add');
    if (line.length > 6 && line[6] === '-') span.classList.add('delete');
    pre.append(span);
  });
  code.append(pre);
  const failure = document.createElement('p'); failure.className = 'block-failure'; failure.textContent = block.failure_message || '';
  const comment = document.createElement('div'); comment.className = 'block-comment';
  const commentTitle = document.createElement('strong'); commentTitle.textContent = '总体评论';
  const commentText = document.createElement('p'); commentText.textContent = block.comment || '无';
  comment.append(commentTitle, commentText);
  const issues = document.createElement('div'); issues.className = 'issue-list';
  if (block.issues.length) issues.append(...block.issues.map((issue) => renderIssue(file, block, issue)));
  else { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = '该 Block 没有有效审核问题。'; issues.append(empty); }
  section.append(heading, code);
  if (block.failure_message) section.append(failure);
  section.append(comment, issues);
  return section;
}

function reviewStatus(status) {
  const names = { completed: '已完成', reviewing: '审核中', pending: '待处理', failed: '失败' };
  const badge = document.createElement('span');
  badge.className = `review-status ${status}`;
  badge.textContent = names[status] || status;
  return badge;
}

function renderIssue(file, block, issue) {
  const item = document.createElement('article'); item.className = 'issue-item';
  const content = document.createElement('div');
  const meta = document.createElement('div'); meta.className = 'issue-meta';
  meta.append(severityBadge(issue.severity));
  const line = document.createElement('span'); line.textContent = `行号 ${issue.issue_line_numbers || '--'}`;
  const type = document.createElement('span'); type.textContent = `类型 ${issue.type || '--'}`;
  meta.append(line, type);
  const copy = document.createElement('div'); copy.className = 'issue-copy';
  copy.append(issueCopy('问题描述', issue.description), issueCopy('修复建议', issue.suggestion));
  content.append(meta, copy);
  const actions = document.createElement('div'); actions.className = 'feedback-actions';
  const agree = feedbackButton('agree', '赞成该问题', '👍', issue.feedback_type === 'agree');
  const reject = feedbackButton('reject', '反对该问题', '👎', issue.feedback_type === 'reject');
  agree.addEventListener('click', () => saveFeedback(file.file_id, block.block_id, issue.issue_id, 'agree', '', actions));
  reject.addEventListener('click', () => openReject(file.file_id, block.block_id, issue.issue_id, actions, issue.feedback_content));
  actions.append(agree, reject);
  item.append(content, actions);
  return item;
}

function issueCopy(title, text) {
  const box = document.createElement('div');
  const heading = document.createElement('h4'); heading.textContent = title;
  const paragraph = document.createElement('p'); paragraph.textContent = text || '--';
  box.append(heading, paragraph); return box;
}

function severityBadge(value) {
  const badge = document.createElement('span'); badge.className = `severity severity-${value}`; badge.textContent = value; return badge;
}

function feedbackButton(type, title, icon, active) {
  const button = document.createElement('button'); button.type = 'button';
  button.className = `feedback-button ${type}${active ? ' active' : ''}`;
  button.title = title; button.setAttribute('aria-label', title); button.textContent = icon; return button;
}

function openReject(fileId, blockId, issueId, actions, existingContent) {
  state.rejectTarget = { fileId, blockId, issueId, actions };
  $('#reject-reason').value = existingContent || '';
  $('#reject-dialog').showModal();
  $('#reject-reason').focus();
}

async function saveFeedback(fileId, blockId, issueId, type, content, actions) {
  [...actions.querySelectorAll('button')].forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(`/api/feedback/${encodeURIComponent(fileId)}/${blockId}/${issueId}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback_type: type, feedback_content: content }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || body.detail?.[0]?.msg || `HTTP ${response.status}`);
    }
    actions.querySelector('.agree').classList.toggle('active', type === 'agree');
    actions.querySelector('.reject').classList.toggle('active', type === 'reject');
    showToast(type === 'agree' ? '已记录赞成反馈' : '已记录反对反馈');
  } catch (error) {
    showToast(`反馈保存失败：${error.message}`);
  } finally {
    [...actions.querySelectorAll('button')].forEach((button) => { button.disabled = false; });
  }
}

function renderPagination(container, pagination) {
  const show = pagination.total_items > pagination.page_size;
  container.hidden = !show;
  if (!show) { container.replaceChildren(); return; }
  const buttons = [];
  buttons.push(pageButton('上一页', pagination.page - 1, pagination.page === 1));
  const first = Math.max(1, pagination.page - 2);
  const last = Math.min(pagination.total_pages, pagination.page + 2);
  for (let page = first; page <= last; page += 1) buttons.push(pageButton(String(page), page, false, page === pagination.page));
  buttons.push(pageButton('下一页', pagination.page + 1, pagination.page === pagination.total_pages));
  container.replaceChildren(...buttons);
}

function pageButton(label, page, disabled, active = false) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.disabled = disabled;
  button.classList.toggle('active', active); button.addEventListener('click', () => { state.page = page; loadReport(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
  return button;
}

async function retryFailedBlocks() {
  const button = $('#retry-failures-button');
  button.disabled = true;
  button.textContent = '正在提交续审...';
  try {
    const response = await fetch(`/tasks/${encodeURIComponent(state.taskId)}/retry-failures`, { method: 'POST' });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${response.status}`);
    }
    showToast('失败项已进入最高优先级重新审核队列');
    await loadReport({ silent: true });
  } catch (error) {
    showToast(`续审提交失败：${error.message}`);
    button.disabled = false;
  }
}

let toastTimer;
function showToast(message) {
  const toast = $('#toast'); toast.textContent = message; toast.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 2600);
}

$('#author-select').addEventListener('change', (event) => { state.author = event.target.value; state.page = 1; loadReport(); });
$('#retry-button').addEventListener('click', loadReport);
$('#retry-failures-button').addEventListener('click', retryFailedBlocks);
$('#reject-cancel').addEventListener('click', () => $('#reject-dialog').close());
$('#reject-close').addEventListener('click', () => $('#reject-dialog').close());
$('#reject-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const reason = $('#reject-reason').value.trim();
  if (!reason) { $('#reject-reason').reportValidity(); return; }
  const target = state.rejectTarget;
  $('#reject-dialog').close();
  if (target) await saveFeedback(target.fileId, target.blockId, target.issueId, 'reject', reason, target.actions);
});
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.scoreDimensions) drawRadar(state.scoreDimensions);
  }, 120);
}, { passive: true });

loadReport();
