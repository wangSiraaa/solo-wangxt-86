async function request(path, options = {}) {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* 保留默认信息 */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

export const api = {
  summary: () => request("/summary/"),
  contracts: () => request("/contracts/"),
  contract: (id) => request(`/contracts/${id}/`),
  periods: () => request("/periods/"),
  closePeriod: (id) => request(`/periods/${id}/close/`, { method: "POST" }),
  reallocate: (id, reason) =>
    request(`/contracts/${id}/reallocate/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  addEvidence: (payload) =>
    request("/evidence/", { method: "POST", body: JSON.stringify(payload) }),
  addUsage: (payload) =>
    request("/usage-records/", { method: "POST", body: JSON.stringify(payload) }),
  addInvoice: (payload) =>
    request("/invoices/", { method: "POST", body: JSON.stringify(payload) }),
  addPayment: (payload) =>
    request("/payments/", { method: "POST", body: JSON.stringify(payload) }),
};
