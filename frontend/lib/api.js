const API_BASE = process.env.NEXT_PUBLIC_API_BASE || process.env.BACKEND_URL || "http://127.0.0.1:8000";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request(path, init) {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const timeoutMs = Number(init?.timeoutMs || 20000);
  const { timeoutMs: _timeoutMs, ...requestInit } = init || {};
  let lastError = null;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        ...requestInit,
        headers: {
          ...(isFormData ? {} : { "Content-Type": "application/json" }),
          ...(requestInit.headers || {}),
        },
        cache: "no-store",
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (!response.ok) {
        const detail = await response.text();
        if (attempt < 2 && response.status >= 500) {
          await sleep(600);
          continue;
        }
        throw new Error(detail || `Request failed for ${path} (status ${response.status})`);
      }
      return response.json();
    } catch (err) {
      clearTimeout(timeout);
      if (err?.name === "AbortError") {
        lastError = new Error(`Request timed out for ${path}`);
        break;
      }
      lastError = err;
      if (attempt < 2) {
        await sleep(600);
        continue;
      }
    }
  }
  throw lastError || new Error(`Request failed for ${path}`);
}

export const api = {
  listJobs: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) q.set(k, String(v));
    });
    return request(`/jobs${q.toString() ? `?${q.toString()}` : ""}`);
  },
  getJob: (id) => request(`/jobs/${id}`),
  updateJob: (id, body) => request(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteJob: (id) => request(`/jobs/${id}`, { method: "DELETE" }),
  bulkAction: (ids, action) => request(`/jobs/bulk-action`, { method: "POST", body: JSON.stringify({ ids, action }) }),
  generateMaterials: (id, body) => request(`/jobs/${id}/materials`, { method: "POST", body: JSON.stringify(body) }),
  generateMaterialsBatch: (body) => request("/jobs/materials/batch", { method: "POST", body: JSON.stringify(body), timeoutMs: 45000 }),
  getMetrics: () => request("/jobs/dashboard/metrics"),
  getRefreshStatus: () => request("/jobs/refresh-status"),
  queueRefreshSources: (body) =>
    request("/jobs/refresh-sources", { method: "POST", body: JSON.stringify(body), timeoutMs: 10000 }),
  ingest: (body) => request("/jobs/ingest", { method: "POST", body: JSON.stringify(body) }),
  searchJobs: (body) => request("/jobs/search", { method: "POST", body: JSON.stringify(body), timeoutMs: 30000 }),
  discoverCompanySites: (body) => request("/jobs/discover-company-sites", { method: "POST", body: JSON.stringify(body) }),
  getRecommendations: (params = {}, options = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) q.set(k, String(v));
    });
    return request(`/jobs/recommendations${q.toString() ? `?${q.toString()}` : ""}`, {
      timeoutMs: Number(options.timeoutMs || 25000),
    });
  },
  getNationalRecommendations: (body) =>
    request("/jobs/recommendations/national", { method: "POST", body: JSON.stringify(body), timeoutMs: 30000 }),
  exportCsv: () => request("/jobs/export/csv"),
  runAutomationNow: () => request("/automation/run-now", { method: "POST" }),
  listSources: () => request("/automation/sources"),
  addSource: (source_type, config, enabled = true) => request("/automation/sources", { method: "POST", body: JSON.stringify({ source_type, config, enabled }) }),
  updateSource: (id, body) => request(`/automation/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  getProfile: () => request("/profile"),
  updateProfile: (body) => request("/profile", { method: "PATCH", body: JSON.stringify(body) }),
  rescoreAllJobs: () => request("/jobs/rescore-all", { method: "POST" }),
  uploadResume: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/profile/resume", { method: "POST", body: form });
  },
};
