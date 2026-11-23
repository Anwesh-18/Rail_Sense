const API_BASE = "http://127.0.0.1:8000/api";
const statusEl = document.getElementById("status");
let latestOtp = null;

async function init() {
  const { token, activeAddress } = await chrome.storage.local.get(["token", "activeAddress"]);
  if (token) {
    document.getElementById("auth-view").classList.add("hidden");
    document.getElementById("main-view").classList.remove("hidden");
  }
  if (activeAddress) showActiveBox(activeAddress);
}

function showActiveBox(address) {
  document.getElementById("active-box").classList.remove("hidden");
  document.getElementById("burnt-address").textContent = address;
}

document.getElementById("login-btn").addEventListener("click", async () => {
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  statusEl.textContent = "Authenticating...";

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  const data = await res.json();
  if (!res.ok) {
    statusEl.textContent = data.detail || "Login failed";
    return;
  }
  await chrome.storage.local.set({ token: data.access_token });
  statusEl.textContent = "Logged in!";
  init();
});

async function sendToActiveTab(payload) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  chrome.tabs.sendMessage(tab.id, payload, (res) => {
    if (chrome.runtime.lastError) {
      statusEl.textContent = "Refresh the target webpage first so the script attaches.";
      return;
    }
    statusEl.textContent = res?.message || "Action completed.";
  });
}

document.getElementById("generate-btn").addEventListener("click", async () => {
  const { token } = await chrome.storage.local.get("token");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let domain = null;
  try { domain = new URL(tab.url).hostname || "local-test"; } catch {}

  statusEl.textContent = "Provisioning burnt email...";
  const res = await fetch(`${API_BASE}/mailboxes/insta-burn`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify({ ttl_seconds: 3600, target_domain: domain })
  });
  const data = await res.json();
  if (!res.ok) {
    statusEl.textContent = data.detail || "Failed to generate";
    return;
  }

  await chrome.storage.local.set({ activeAddress: data.address });
  showActiveBox(data.address);
  await sendToActiveTab({ action: "STEALTH_FILL", email: data.address });
});

document.getElementById("refill-btn").addEventListener("click", async () => {
  const { activeAddress } = await chrome.storage.local.get("activeAddress");
  if (activeAddress) await sendToActiveTab({ action: "STEALTH_FILL", email: activeAddress });
});

document.getElementById("check-otp-btn").addEventListener("click", async () => {
  const { token, activeAddress } = await chrome.storage.local.get(["token", "activeAddress"]);
  if (!activeAddress) return;

  statusEl.textContent = "Polling inbox...";
  const res = await fetch(`${API_BASE}/mailboxes/${encodeURIComponent(activeAddress)}/messages`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  const messages = await res.json();
  document.getElementById("inbox-box").classList.remove("hidden");

  if (!messages.length) {
    statusEl.textContent = "No messages received yet.";
    return;
  }
  const latest = messages[0];
  latestOtp = latest.extracted_otp;
  document.getElementById("otp-val").textContent = latestOtp || "None";

  const fillOtpBtn = document.getElementById("fill-otp-btn");
  if (latestOtp) fillOtpBtn.classList.remove("hidden");
  else fillOtpBtn.classList.add("hidden");

  document.getElementById("link-val").innerHTML = latest.verification_link
    ? `<a href="${latest.verification_link}" target="_blank" style="color:#38bdf8;">Open Verification Link</a>`
    : "";
  statusEl.textContent = `Latest email from ${latest.sender}`;
});

document.getElementById("fill-otp-btn").addEventListener("click", async () => {
  if (latestOtp) await sendToActiveTab({ action: "FILL_OTP", otp: latestOtp });
});

document.getElementById("burn-btn").addEventListener("click", async () => {
  const { token, activeAddress } = await chrome.storage.local.get(["token", "activeAddress"]);
  if (!activeAddress) return;

  await fetch(`${API_BASE}/mailboxes/${encodeURIComponent(activeAddress)}`, {
    method: "DELETE",
    headers: { "Authorization": `Bearer ${token}` }
  });
  await chrome.storage.local.remove("activeAddress");
  document.getElementById("active-box").classList.add("hidden");
  document.getElementById("inbox-box").classList.add("hidden");
  statusEl.textContent = "Mailbox burned & purged.";
});

init();