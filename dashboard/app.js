// ─── Configuration ──────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:3000';
const POLL_INTERVAL = 3000;

// ─── API Client ─────────────────────────────────────────────────────────────
const api = {
    async request(method, path, body) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`${API_BASE}${path}`, opts);
        return res.json();
    },
    listPipelines()          { return this.request('GET', '/api/status'); },
    getPipeline(key)         { return this.request('GET', `/api/status/${encodeURIComponent(key)}`); },
    getLogs(key, agent)      {
        const q = agent && agent !== 'all' ? `?agent=${encodeURIComponent(agent)}` : '';
        return this.request('GET', `/api/status/${encodeURIComponent(key)}/logs${q}`);
    },
    trigger(data)            { return this.request('POST', '/api/trigger', data); },
    cancel(key)              { return this.request('DELETE', `/api/status/${encodeURIComponent(key)}`); },
};

// ─── State ──────────────────────────────────────────────────────────────────
let pollTimer = null;
let pollActive = true;

// ─── Router ─────────────────────────────────────────────────────────────────
function route() {
    stopPolling();
    const hash = location.hash.slice(1) || 'pipelines';
    const parts = hash.split('/');
    const view = parts[0];
    const param = parts.slice(1).join('/');

    // Update active nav
    document.querySelectorAll('.nav-link').forEach(el => {
        el.classList.toggle('active', el.dataset.route === view);
    });

    switch (view) {
        case 'pipelines': renderPipelineList(); break;
        case 'trigger':   renderTriggerForm();  break;
        case 'pipeline':  renderPipelineDetail(param); break;
        case 'logs':      renderLogs(param); break;
        default:          renderPipelineList(); break;
    }
}

window.addEventListener('hashchange', route);
window.addEventListener('DOMContentLoaded', route);

// ─── Polling ────────────────────────────────────────────────────────────────
function startPolling(fn) {
    if (!pollActive) return;
    pollTimer = setInterval(() => {
        if (pollActive) fn();
    }, POLL_INTERVAL);
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

// Live indicator toggle
document.addEventListener('DOMContentLoaded', () => {
    const indicator = document.getElementById('live-indicator');
    if (indicator) {
        indicator.addEventListener('click', () => {
            pollActive = !pollActive;
            const dot = indicator.querySelector('.live-dot');
            const text = document.getElementById('live-text');
            dot.classList.toggle('paused', !pollActive);
            text.textContent = pollActive ? 'Live' : 'Paused';
            if (!pollActive) stopPolling();
        });
    }
});

// ─── Helpers ────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function stateBadge(state) {
    const s = (state || 'unknown').replace(/\s+/g, '-');
    return `<span class="badge badge-${s}">${s}</span>`;
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString();
}

function showToast(msg, type = 'success') {
    const container = $('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

function setApp(html) {
    $('app').innerHTML = html;
}

// ─── View: Pipeline List ────────────────────────────────────────────────────
async function renderPipelineList() {
    setApp(`
        <div class="flex items-center justify-between mb-6">
            <h2 class="text-2xl font-bold">Pipelines</h2>
        </div>
        <div id="pipeline-list-content">
            <p class="text-gray-400">Loading...</p>
        </div>
    `);
    await fetchAndRenderList();
    startPolling(fetchAndRenderList);
}

async function fetchAndRenderList() {
    try {
        const data = await api.listPipelines();
        const target = $('pipeline-list-content');
        if (!target) return;

        if (!data.pipelines || data.pipelines.length === 0) {
            target.innerHTML = `
                <div class="text-center py-16 text-gray-400">
                    <svg class="w-12 h-12 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>
                    <p class="text-lg font-medium">No pipelines found</p>
                    <p class="mt-1">Trigger one to get started.</p>
                    <a href="#trigger" class="inline-block mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Trigger Pipeline</a>
                </div>`;
            return;
        }

        const rows = data.pipelines.map(p => `
            <tr>
                <td class="font-medium">${esc(p.issueKey)}</td>
                <td>${stateBadge(p.state)}</td>
                <td class="text-xs font-mono text-gray-500">${esc(p.branch)}</td>
                <td class="text-sm text-gray-500">${formatDate(p.createdAt)}</td>
                <td class="text-sm text-gray-500">${formatDate(p.updatedAt)}</td>
                <td class="text-center">${p.reworkCount || 0}</td>
                <td>
                    <div class="flex gap-2">
                        <a href="#pipeline/${esc(p.issueKey)}" class="text-blue-600 hover:text-blue-800 text-sm font-medium">View</a>
                        <a href="#logs/${esc(p.issueKey)}" class="text-indigo-600 hover:text-indigo-800 text-sm font-medium">Logs</a>
                        <button onclick="cancelPipeline('${esc(p.issueKey)}')" class="text-red-600 hover:text-red-800 text-sm font-medium">Cancel</button>
                    </div>
                </td>
            </tr>
        `).join('');

        target.innerHTML = `
            <div class="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
                <table class="pipeline-table">
                    <thead>
                        <tr>
                            <th>Issue Key</th>
                            <th>State</th>
                            <th>Branch</th>
                            <th>Created</th>
                            <th>Updated</th>
                            <th>Reworks</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <p class="text-xs text-gray-400 mt-2">${data.count} pipeline(s)</p>
        `;
    } catch (err) {
        const target = $('pipeline-list-content');
        if (target) {
            target.innerHTML = `<p class="text-red-500">Failed to load pipelines: ${esc(err.message)}</p>`;
        }
    }
}

// ─── View: Pipeline Detail ──────────────────────────────────────────────────
async function renderPipelineDetail(issueKey) {
    setApp(`<p class="text-gray-400">Loading...</p>`);
    await fetchAndRenderDetail(issueKey);
    startPolling(() => fetchAndRenderDetail(issueKey));
}

async function fetchAndRenderDetail(issueKey) {
    try {
        const p = await api.getPipeline(issueKey);
        const target = $('app');
        if (!target) return;

        if (p.error) {
            target.innerHTML = `
                <div class="mb-4"><a href="#pipelines" class="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Pipelines</a></div>
                <p class="text-red-500">${esc(p.error)}</p>`;
            return;
        }

        target.innerHTML = `
            <div class="mb-4"><a href="#pipelines" class="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Pipelines</a></div>
            <div class="flex items-center gap-4 mb-6">
                <h2 class="text-2xl font-bold">${esc(p.issueKey)}</h2>
                ${stateBadge(p.state)}
            </div>
            <div class="detail-card mb-6">
                <div class="detail-field"><span class="detail-label">Branch</span><span class="detail-value font-mono text-sm">${esc(p.branch)}</span></div>
                <div class="detail-field"><span class="detail-label">Repo Path</span><span class="detail-value font-mono text-sm">${esc(p.repoPath || '—')}</span></div>
                <div class="detail-field"><span class="detail-label">Created</span><span class="detail-value">${formatDate(p.createdAt)}</span></div>
                <div class="detail-field"><span class="detail-label">Updated</span><span class="detail-value">${formatDate(p.updatedAt)}</span></div>
                <div class="detail-field"><span class="detail-label">Rework Count</span><span class="detail-value">${p.reworkCount || 0}</span></div>
            </div>
            <div class="flex gap-3">
                <a href="#logs/${esc(p.issueKey)}" class="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700">View Logs</a>
                <button onclick="cancelPipeline('${esc(p.issueKey)}')" class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700">Cancel Pipeline</button>
            </div>
        `;
    } catch (err) {
        const target = $('app');
        if (target) {
            target.innerHTML = `<p class="text-red-500">Failed to load pipeline: ${esc(err.message)}</p>`;
        }
    }
}

// ─── View: Logs ─────────────────────────────────────────────────────────────
let currentLogAgent = 'all';
let autoScroll = true;

async function renderLogs(issueKey) {
    currentLogAgent = 'all';
    autoScroll = true;

    setApp(`
        <div class="mb-4"><a href="#pipeline/${esc(issueKey)}" class="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Pipeline</a></div>
        <div class="flex items-center justify-between mb-4">
            <h2 class="text-2xl font-bold">Logs: ${esc(issueKey)}</h2>
            <div class="flex items-center gap-3">
                <label class="text-sm text-gray-600">Agent:</label>
                <select id="agent-filter" class="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <option value="all">All</option>
                    <option value="orchestrator">orchestrator</option>
                    <option value="brainstorm">brainstorm</option>
                    <option value="developer">developer</option>
                    <option value="feedback-parser">feedback-parser</option>
                </select>
            </div>
        </div>
        <div id="log-output" class="log-viewer"></div>
        <p id="log-lines" class="text-xs text-gray-400 mt-2"></p>
    `);

    const select = $('agent-filter');
    if (select) {
        select.addEventListener('change', () => {
            currentLogAgent = select.value;
            fetchAndRenderLogs(issueKey);
        });
    }

    const logEl = $('log-output');
    if (logEl) {
        logEl.addEventListener('scroll', () => {
            const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 50;
            autoScroll = atBottom;
        });
    }

    await fetchAndRenderLogs(issueKey);
    startPolling(() => fetchAndRenderLogs(issueKey));
}

async function fetchAndRenderLogs(issueKey) {
    try {
        const data = await api.getLogs(issueKey, currentLogAgent);
        const logEl = $('log-output');
        const linesEl = $('log-lines');
        if (!logEl) return;

        logEl.textContent = data.output || '(no output yet)';
        if (linesEl) linesEl.textContent = `${data.lines || 0} lines | Agent: ${data.agent}`;

        if (autoScroll) {
            logEl.scrollTop = logEl.scrollHeight;
        }
    } catch (err) {
        const logEl = $('log-output');
        if (logEl) logEl.textContent = `Error loading logs: ${err.message}`;
    }
}

// ─── View: Trigger Form ─────────────────────────────────────────────────────
function renderTriggerForm() {
    setApp(`
        <h2 class="text-2xl font-bold mb-6">Trigger Pipeline</h2>
        <div class="detail-card max-w-lg">
            <form id="trigger-form" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Issue Key <span class="text-red-500">*</span></label>
                    <input type="text" id="f-issueKey" required placeholder="PROJ-42"
                        class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Summary</label>
                    <input type="text" id="f-summary" placeholder="Add login page"
                        class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Component</label>
                    <input type="text" id="f-component" placeholder="frontend-app"
                        class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <div id="trigger-result"></div>
                <button type="submit" id="trigger-btn"
                    class="w-full px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
                    Trigger Pipeline
                </button>
            </form>
        </div>
    `);

    $('trigger-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = $('trigger-btn');
        const result = $('trigger-result');
        btn.disabled = true;
        btn.textContent = 'Triggering...';

        const payload = { issueKey: $('f-issueKey').value.trim() };
        const summary = $('f-summary').value.trim();
        const component = $('f-component').value.trim();
        if (summary) payload.summary = summary;
        if (component) payload.component = component;

        try {
            const data = await api.trigger(payload);
            if (data.accepted) {
                result.innerHTML = `
                    <div class="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
                        Pipeline started for <strong>${esc(data.issueKey)}</strong> on branch <code class="text-xs">${esc(data.branch)}</code>.
                        <a href="#pipeline/${esc(data.issueKey)}" class="underline font-medium ml-1">View pipeline</a>
                    </div>`;
                showToast('Pipeline triggered successfully');
            } else if (data.error) {
                result.innerHTML = `<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">${esc(data.error)}</div>`;
                showToast(data.error, 'error');
            }
        } catch (err) {
            result.innerHTML = `<div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">Request failed: ${esc(err.message)}</div>`;
            showToast('Failed to trigger pipeline', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Trigger Pipeline';
        }
    });
}

// ─── Actions ────────────────────────────────────────────────────────────────
async function cancelPipeline(issueKey) {
    if (!confirm(`Cancel pipeline for ${issueKey}? This will delete state and logs.`)) return;
    try {
        const data = await api.cancel(issueKey);
        if (data.cancelled) {
            showToast(`Pipeline ${issueKey} cancelled`);
            location.hash = '#pipelines';
            route();
        } else {
            showToast(data.error || 'Failed to cancel', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// ─── Utilities ──────────────────────────────────────────────────────────────
function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}
