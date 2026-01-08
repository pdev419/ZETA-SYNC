async function refreshStatus() {
  const r = await fetch("/api/v1/cluster/status");
  document.getElementById("status").innerText = JSON.stringify(await r.json(), null, 2);
}

async function startSync() {
  await fetch("/mgmt/cluster/start", { method: "POST" });
  refreshStatus();
}

async function stopSync() {
  await fetch("/mgmt/cluster/stop", { method: "POST" });
  refreshStatus();
}

setInterval(refreshStatus, 1000);
refreshStatus();
