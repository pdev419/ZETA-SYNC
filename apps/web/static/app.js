// apps/web/static/app.js

function escapeHtml(s){
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));
}

async function apiCall(method, url, body){
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : {}; } catch { json = { raw: text }; }
  if (!res.ok) {
    const msg = (json && (json.detail || json.error)) ? (json.detail || json.error) : (text || res.statusText);
    throw new Error(msg);
  }
  return json;
}

function setActiveNav(){
  const path = location.pathname;
  document.querySelectorAll(".nav a").forEach(a=>{
    const href = a.getAttribute("href");
    if (!href) return;
    if (href === path) a.classList.add("active");
    else a.classList.remove("active");
  });
}

function pillHtml(text, kind){
  // kind: ok | warn | bad
  const cls = kind ? `pill ${kind}` : "pill";
  return `<span class="${cls}"><span class="dot"></span>${escapeHtml(text)}</span>`;
}

function toFixedMaybe(v, digits=6){
  if (typeof v === "number") return v.toFixed(digits);
  if (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v))) return Number(v).toFixed(digits);
  return v ?? "";
}

function copyTextFromEl(id){
  const t = (document.getElementById(id)?.textContent || "").trim();
  if (!t) return alert("Nothing to copy");
  navigator.clipboard.writeText(t);
  alert("Copied");
}

// Authority bundle helper (used by security.html)
async function authorityIssueBundle(authorityUrl, nodeId, token){
  const url = authorityUrl.replace(/\/+$/,"") + "/mgmt/security/bootstrap/issue";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type":"application/json" },
    body: JSON.stringify({ node_id: nodeId, token })
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : {}; } catch { json = { raw: text }; }
  if (!res.ok) {
    const msg = (json && (json.detail || json.error)) ? (json.detail || json.error) : (text || res.statusText);
    throw new Error(msg);
  }
  return json;
}

window.addEventListener("DOMContentLoaded", () => setActiveNav());
