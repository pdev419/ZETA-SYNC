let _basicAuthHeader = null;

function escapeHtml(str) {
  return (str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function ensureAuth() {
  if (_basicAuthHeader) return _basicAuthHeader;

  const user = prompt("Admin username:", "admin");
  const pass = prompt("Admin password:", "admin123");
  if (user == null || pass == null) throw new Error("Cancelled");

  _basicAuthHeader = "Basic " + btoa(user + ":" + pass);
  return _basicAuthHeader;
}

async function apiCall(method, url, body = null) {
  const headers = { "Content-Type": "application/json" };
  headers["Authorization"] = ensureAuth();

  const opts = { method, headers };
  if (body !== null) opts.body = JSON.stringify(body);

  const res = await fetch(url, opts);

  if (res.status === 401) {
    _basicAuthHeader = null;
    alert("Unauthorized. Please try again.");
    throw new Error("Unauthorized");
  }

  const text = await res.text();
  try { return JSON.parse(text); } catch { return { raw: text, status: res.status }; }
}

/**
 * Authority provisioning call:
 * - Does NOT use Basic auth (protected by bootstrap token)
 * - POST { node_id, token } to Authority URL
 */
async function authorityIssueBundle(authorityBaseUrl, nodeId, token) {
  const url = authorityBaseUrl.replace(/\/+$/, "") + "/mgmt/security/bootstrap/issue";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId, token })
  });
  const text = await res.text();
  let obj;
  try { obj = JSON.parse(text); } catch { obj = { raw: text, status: res.status }; }

  if (!res.ok) {
    throw new Error(obj.detail || obj.reason || ("Authority error: " + res.status));
  }
  return obj;
}
