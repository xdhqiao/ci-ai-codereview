const dashboardState = {
  data: null,
  chartColors: ['#087f5b', '#168aad', '#d97706', '#7b8790', '#c2413a'],
};

const numberFormatter = new Intl.NumberFormat('zh-CN');

document.addEventListener('DOMContentLoaded', () => {
  initializeDates();
  document.getElementById('dashboard-filter').addEventListener('submit', (event) => {
    event.preventDefault();
    loadDashboard();
  });
  document.getElementById('reset-range').addEventListener('click', () => {
    setRecentRange();
    loadDashboard();
  });
  document.getElementById('retry-load').addEventListener('click', loadDashboard);
  window.addEventListener('resize', () => {
    if (dashboardState.data) {
      drawTaskTypeChart(dashboardState.data.tasks.task_types);
    }
  });
  loadDashboard();
});

function initializeDates() {
  const params = new URLSearchParams(window.location.search);
  const start = params.get('start_date');
  const end = params.get('end_date');
  if (start && end) {
    document.getElementById('start-date').value = start;
    document.getElementById('end-date').value = end;
    return;
  }
  setRecentRange();
}

function setRecentRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 29);
  document.getElementById('start-date').value = localDateValue(start);
  document.getElementById('end-date').value = localDateValue(end);
}

function localDateValue(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function loadDashboard() {
  const startDate = document.getElementById('start-date').value;
  const endDate = document.getElementById('end-date').value;
  const errorState = document.getElementById('error-state');
  const loadingState = document.getElementById('loading-state');
  const content = document.getElementById('dashboard-content');

  if (!startDate || !endDate || startDate > endDate) {
    showError('开始日期不能晚于结束日期。');
    return;
  }

  errorState.hidden = true;
  content.hidden = true;
  loadingState.hidden = false;

  const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
  history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`);
  try {
    const response = await fetch(`/api/admin/dashboard?${params.toString()}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || payload.detail || `HTTP ${response.status}`);
    }
    const data = await response.json();
    dashboardState.data = data;
    renderDashboard(data);
    loadingState.hidden = true;
    content.hidden = false;
  } catch (error) {
    loadingState.hidden = true;
    showError(error.message || '未知错误');
  }
}

function showError(message) {
  document.getElementById('dashboard-content').hidden = true;
  document.getElementById('loading-state').hidden = true;
  document.getElementById('error-message').textContent = message;
  document.getElementById('error-state').hidden = false;
}

function renderDashboard(data) {
  document.getElementById('range-summary').textContent =
    `${data.start_date} 至 ${data.end_date}，共 ${data.tasks.task_count} 个审核任务。`;
  setNumber('task-count', data.tasks.task_count);
  setNumber('project-count', data.tasks.project_count);
  setNumber('chart-total', data.tasks.task_count);

  setNumber('total-tokens', data.resources.total_tokens);
  setNumber('prompt-tokens', data.resources.prompt_tokens);
  setNumber('completion-tokens', data.resources.completion_tokens);
  document.getElementById('llm-elapsed').textContent = formatDuration(data.resources.llm_elapsed_ms);
  document.getElementById('llm-elapsed').title = `${numberFormatter.format(data.resources.llm_elapsed_ms)} ms`;
  setNumber('file-count', data.resources.file_count);
  setNumber('reviewed-file-count', data.resources.reviewed_file_count);
  setNumber('tool-call-count', data.resources.tool_call_count);
  setNumber('model-round-count', data.resources.model_round_count);

  setNumber('valid-issue-count', data.issues.valid_issue_count);
  setNumber('filtered-issue-count', data.issues.filtered_issue_count);
  setNumber('severe-issue-count', data.issues.severe_issue_count);

  setNumber('feedback-count', data.feedback.feedback_count);
  setNumber('agree-count', data.feedback.agree_count);
  setRate('agree-rate', 'agree-rate-bar', data.feedback.agree_rate);
  setNumber('historical-feedback-count', data.feedback.historical_feedback_count);
  setNumber('historical-agree-count', data.feedback.historical_agree_count);
  setRate(
    'historical-agree-rate',
    'historical-agree-rate-bar',
    data.feedback.historical_agree_rate,
  );

  renderTaskTypeLegend(data.tasks.task_types, data.tasks.task_count);
  requestAnimationFrame(() => drawTaskTypeChart(data.tasks.task_types));
}

function setNumber(id, value) {
  document.getElementById(id).textContent = numberFormatter.format(value || 0);
}

function setRate(labelId, barId, value) {
  const rate = Math.min(100, Math.max(0, Number(value) || 0));
  document.getElementById(labelId).textContent = `${rate.toFixed(1)}%`;
  document.getElementById(barId).style.width = `${rate}%`;
}

function formatDuration(milliseconds) {
  const seconds = Math.round((milliseconds || 0) / 1000);
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes} 分 ${remainingSeconds} 秒`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours} 小时 ${remainingMinutes} 分`;
}

function renderTaskTypeLegend(items, total) {
  const legend = document.getElementById('task-type-legend');
  legend.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('li');
    empty.className = 'legend-label';
    empty.textContent = '当前区间暂无任务';
    legend.appendChild(empty);
    return;
  }

  items.forEach((item, index) => {
    const row = document.createElement('li');
    const dot = document.createElement('span');
    dot.className = 'legend-dot';
    dot.style.background = dashboardState.chartColors[index % dashboardState.chartColors.length];
    const label = document.createElement('span');
    label.className = 'legend-label';
    const percent = total ? (item.count * 100 / total).toFixed(1) : '0.0';
    label.textContent = `${item.label} · ${percent}%`;
    const value = document.createElement('span');
    value.className = 'legend-value';
    value.textContent = numberFormatter.format(item.count);
    row.append(dot, label, value);
    legend.appendChild(row);
  });
}

function drawTaskTypeChart(items) {
  const canvas = document.getElementById('task-type-chart');
  const displaySize = Math.min(canvas.clientWidth || 220, canvas.clientHeight || 220);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(displaySize * ratio);
  canvas.height = Math.round(displaySize * ratio);
  const context = canvas.getContext('2d');
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, displaySize, displaySize);

  const center = displaySize / 2;
  const radius = displaySize * 0.43;
  const innerRadius = displaySize * 0.29;
  const total = items.reduce((sum, item) => sum + item.count, 0);
  if (!total) {
    drawSegment(context, center, radius, innerRadius, 0, Math.PI * 2, '#e2e7e4');
    return;
  }

  let angle = -Math.PI / 2;
  items.forEach((item, index) => {
    const slice = item.count / total * Math.PI * 2;
    drawSegment(
      context,
      center,
      radius,
      innerRadius,
      angle,
      angle + slice,
      dashboardState.chartColors[index % dashboardState.chartColors.length],
    );
    angle += slice;
  });
}

function drawSegment(context, center, radius, innerRadius, startAngle, endAngle, color) {
  context.beginPath();
  context.arc(center, center, radius, startAngle, endAngle);
  context.arc(center, center, innerRadius, endAngle, startAngle, true);
  context.closePath();
  context.fillStyle = color;
  context.fill();
}
