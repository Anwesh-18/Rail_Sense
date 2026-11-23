const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const randomDelay = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;

function setNativeValue(element, value) {
  const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else if (valueSetter) {
    valueSetter.call(element, value);
  } else {
    element.value = value;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function humanType(input, text) {
  input.focus();
  let current = "";
  for (const char of text) {
    current += char;
    setNativeValue(input, current);
    await sleep(randomDelay(35, 95));
  }
  input.blur();
}

function showConfirmationBanner(message) {
  const existing = document.getElementById("burnt-mail-confirm-banner");
  if (existing) existing.remove();

  const banner = document.createElement("div");
  banner.id = "burnt-mail-confirm-banner";
  banner.style.cssText = `
    position: fixed; bottom: 20px; right: 20px; z-index: 999999;
    background: #0f172a; color: #f8fafc; padding: 14px 18px;
    border-radius: 10px; border: 1px solid #38bdf8; font-family: system-ui, sans-serif;
    box-shadow: 0 10px 25px rgba(0,0,0,0.4); font-size: 13px;
  `;
  banner.innerHTML = `
    <div style="font-weight:600; color:#38bdf8; margin-bottom:6px;">Burnt Mail Automation</div>
    <div>${message}</div>
    <button id="bm-dismiss" style="margin-top:8px; padding:4px 10px; background:#334155; color:#fff; border:none; border-radius:4px; cursor:pointer;">Dismiss</button>
  `;
  document.body.appendChild(banner);
  document.getElementById("bm-dismiss").onclick = () => banner.remove();
}

async function fillDetectedForms(burntEmail) {
  const inputs = Array.from(document.querySelectorAll("input:not([type='hidden']):not([disabled])"));
  const profileMap = [
    { match: /email|e-mail/i, value: burntEmail },
    { match: /first[_-]?name|fname/i, value: "Alex" },
    { match: /last[_-]?name|lname/i, value: "Mercer" },
    { match: /user[_-]?name|login/i, value: burntEmail.split("@")[0] },
    { match: /zip|postal/i, value: "751024" }
  ];

  let filledCount = 0;
  for (const input of inputs) {
    const signature = `${input.type} ${input.name} ${input.id} ${input.placeholder} ${input.autocomplete}`;
    const rule = profileMap.find((r) => r.match.test(signature));
    if (rule && !input.value) {
      await sleep(randomDelay(500, 1200)); // SRS REQ-7 delay pacing
      await humanType(input, rule.value);
      filledCount++;
    }
  }

  if (filledCount > 0) {
    showConfirmationBanner(`Populated ${filledCount} field(s) with stealth delay. Review before submitting.`);
  }
  return filledCount;
}

async function fillOtpField(otp) {
  const inputs = Array.from(document.querySelectorAll("input:not([type='hidden']):not([disabled])"));

  const candidates = inputs.filter((i) => {
    const sig = `${i.name} ${i.id} ${i.placeholder} ${i.autocomplete}`;
    return !/zip|postal|email|name|user|pass|address/i.test(sig);
  });

  const otpInput =
    candidates.find((i) =>
      /one-time-code|otp|verification|2fa|mfa|pin/i.test(`${i.name} ${i.id} ${i.placeholder} ${i.autocomplete}`)
    ) ||
    candidates.find((i) =>
      /code|token/i.test(`${i.name} ${i.id} ${i.placeholder} ${i.autocomplete}`)
    );

  if (!otpInput) return false;
  await humanType(otpInput, otp);
  showConfirmationBanner(`Injected OTP (${otp}) into verification field.`);
  return true;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "STEALTH_FILL") {
    fillDetectedForms(msg.email).then((count) => {
      sendResponse({ message: count ? `Filled ${count} field(s) safely.` : "No matching fields found on page." });
    });
    return true;
  }
  if (msg.action === "FILL_OTP") {
    fillOtpField(msg.otp).then((ok) => {
      sendResponse({ message: ok ? "OTP injected into form!" : "No OTP input field found on page." });
    });
    return true;
  }
});