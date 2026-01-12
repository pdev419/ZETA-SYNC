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

  // If wrong creds, reset auth and allow retry
  if (res.status === 401) {
    _basicAuthHeader = null;
    alert("Unauthorized. Please try again.");
    throw new Error("Unauthorized");
  }

  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text, status: res.status };
  }
}
