async function apiCall(method, url, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const res = await fetch(url, opt);
  const txt = await res.text();
  let data;
  try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
  if (!res.ok) throw new Error((data && data.detail) ? data.detail : ("HTTP " + res.status));
  return data;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setBadge(id, status){
  const el = document.getElementById(id);
  if(!el) return;
  el.textContent = status;

  const s = String(status||"").toLowerCase();
  el.className = "badge";
  if (s.includes("healthy")) el.classList.add("pill","healthy");
  else if (s.includes("degraded")) el.classList.add("pill","degraded");
  else if (s.includes("recover")) el.classList.add("pill","recovering");
  else if (s.includes("offline")) el.classList.add("pill","offline");
}

async function authorityIssueBundle(authorityUrl, nodeId, token){
  const url = authorityUrl.replace(/\/+$/,"") + "/mgmt/security/bootstrap/issue";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type":"application/json" },
    body: JSON.stringify({ node_id: nodeId, token })
  });
  const data = await res.json();
  if(!res.ok) throw new Error(data.detail || "Authority issue failed");
  return data;
}
