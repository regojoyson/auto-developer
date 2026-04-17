const API_BASE = 'http://localhost:3000';

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
  listPipelines() {
    return this.request('GET', '/api/status');
  },
  getPipeline(key) {
    return this.request('GET', `/api/status/${encodeURIComponent(key)}`);
  },
  getLogs(key, agent) {
    const q = agent && agent !== 'all' ? `?agent=${encodeURIComponent(agent)}` : '';
    return this.request('GET', `/api/status/${encodeURIComponent(key)}/logs${q}`);
  },
  trigger(data) {
    return this.request('POST', '/api/trigger', data);
  },
  stop(key) {
    return this.request('POST', `/api/status/${encodeURIComponent(key)}/stop`);
  },
  cancel(key) {
    return this.request('DELETE', `/api/status/${encodeURIComponent(key)}`);
  },
};

export default api;
