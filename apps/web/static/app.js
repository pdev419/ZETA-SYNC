let _basicAuthHeader = null;

function escapeHtml(str) {
  return (str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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
