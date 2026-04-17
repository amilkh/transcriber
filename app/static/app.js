const micButton       = document.getElementById("micButton");
const micDeviceSelect = document.getElementById("micDevice");
const transcript      = document.getElementById("transcript");
const languageSelect  = document.getElementById("language");
const targetLangSelect = document.getElementById("targetLang");
const qaMessages      = document.getElementById("qa-messages");
const qaInput         = document.getElementById("qa-input");
const qaSend          = document.getElementById("qa-send");
const themeToggle     = document.getElementById("themeToggle");

// ---------------------------------------------------------------------------
// Dark / light theme toggle
// ---------------------------------------------------------------------------

function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  themeToggle.textContent = dark ? "Light" : "Dark";
  localStorage.setItem("theme", dark ? "dark" : "light");
}

const savedTheme = localStorage.getItem("theme");
applyTheme(savedTheme !== "light");  // dark by default

themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.getAttribute("data-theme") !== "dark");
});

// ?view  → read-only viewer (students / professor)
const isViewer = new URLSearchParams(location.search).has("view");

const PREFERRED_MIC = "AT2020USB-X";

let ws;
let audioContext;
let mediaStream;
let sourceNode;
let workletNode;
let isRunning = false;
let partialEl = null;
let lastFinalText = "";
let autoPreferredLang = "";
let autoPreferredUntil = 0;
let autoOppositeStreak = 0;

// Prefer Japanese: lock for 15 s, need 4 consecutive opposite-language finals to switch
const AUTO_PREFERRED_MS  = 15000;
const AUTO_SWITCH_STREAK = 4;

// ---------------------------------------------------------------------------
// Mic device enumeration
// ---------------------------------------------------------------------------

async function populateMicDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs  = devices.filter((d) => d.kind === "audioinput");
    // Restore saved id, or fall back to current selection
    const saved = localStorage.getItem("preferredMicId");
    const prev  = micDeviceSelect.value || saved;
    micDeviceSelect.innerHTML = "";
    const def = document.createElement("option");
    def.value = "";
    def.textContent = "Default Mic";
    micDeviceSelect.appendChild(def);
    let preferredId = null;
    inputs.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      opt.textContent = d.label || `Microphone ${i + 1}`;
      micDeviceSelect.appendChild(opt);
      if (!preferredId && d.label.includes(PREFERRED_MIC)) preferredId = d.deviceId;
    });
    if (prev && [...micDeviceSelect.options].some((o) => o.value === prev)) {
      micDeviceSelect.value = prev;
    } else if (preferredId) {
      micDeviceSelect.value = preferredId;
    }
  } catch (_) { /* permission not yet granted */ }
}

function saveMicPreference() {
  localStorage.setItem("preferredMicId", micDeviceSelect.value);
}

// ---------------------------------------------------------------------------
// Transcript rendering
// ---------------------------------------------------------------------------

function addStatusLine(text) {
  const el = document.createElement("div");
  el.className = "status-line";
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

function addErrorLine(text) {
  const el = document.createElement("div");
  el.className = "error-line";
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

function clearPartial() {
  if (partialEl) { partialEl.remove(); partialEl = null; }
}

function updatePartial(text) {
  if (!text) { clearPartial(); return; }
  if (!partialEl) {
    partialEl = document.createElement("div");
    partialEl.className = "partial";
    transcript.appendChild(partialEl);
  }
  // Never go backwards — only update if new text is longer or similar length
  if (partialEl.textContent && text.length < partialEl.textContent.length * 0.75) return;
  partialEl.textContent = text;
  transcript.scrollTop = transcript.scrollHeight;
}

function addFinalEntry(text, detectedLang) {
  if (!text || text === lastFinalText) return;
  const selectedLang = languageSelect.value;
  if (selectedLang === "auto") updateAutoLanguagePreference(text, detectedLang);
  if (shouldSuppressFinal(text, detectedLang, selectedLang)) return;
  lastFinalText = text;
  clearPartial();

  const entry = document.createElement("div");
  entry.className = "entry";

  const jaEl = document.createElement("div");
  jaEl.className = "entry-ja";
  jaEl.textContent = text;
  entry.appendChild(jaEl);

  transcript.appendChild(entry);
  transcript.scrollTop = transcript.scrollHeight;

  const shouldTranslate = selectedLang === "ja" ||
    detectedLang === "ja" ||
    (selectedLang === "auto" && looksJapanese(text));
  if (!shouldTranslate) return;

  const enEl = document.createElement("div");
  enEl.className = "entry-en loading";
  enEl.textContent = "…";
  entry.appendChild(enEl);

  (async () => {
    try {
      const resp = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, target_lang: targetLangSelect.value }),
      });
      if (!resp.ok || !resp.body) { enEl.remove(); return; }
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      enEl.className = "entry-en";
      enEl.textContent = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        enEl.textContent += dec.decode(value, { stream: true });
        transcript.scrollTop = transcript.scrollHeight;
      }
      if (!enEl.textContent.trim()) enEl.remove();
    } catch (_) { enEl.remove(); }
  })();
}

function looksJapanese(text) {
  return /[\u3000-\u9fff\uff00-\uffef]/.test(text);
}
function looksEnglish(text) {
  return /[A-Za-z]/.test(text) && !looksJapanese(text);
}
function inferLanguage(text, detectedLang) {
  if (detectedLang === "ja" || detectedLang === "en") return detectedLang;
  if (looksJapanese(text)) return "ja";
  if (looksEnglish(text))  return "en";
  return "";
}

// Auto-mode starts locked to Japanese; requires 4 consecutive other-language
// finals before switching — so incidental English words don't break the flow.
function resetAutoLanguageLock() {
  autoPreferredLang  = languageSelect.value === "auto" ? "ja" : "";
  autoPreferredUntil = autoPreferredLang ? Date.now() + AUTO_PREFERRED_MS : 0;
  autoOppositeStreak = 0;
}

function pushLanguageConfig(lang) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "config", language: lang }));
  }
}

function setAutoLanguagePreference(nextLang, announce) {
  autoPreferredLang  = nextLang;
  autoPreferredUntil = Date.now() + AUTO_PREFERRED_MS;
  autoOppositeStreak = 0;
  if (announce) addStatusLine(`[auto] switched to ${nextLang === "ja" ? "Japanese" : "English"}`);
}

function updateAutoLanguagePreference(text, detectedLang) {
  const inferred = inferLanguage(text, detectedLang);
  if (!inferred) return;

  if (!autoPreferredLang || Date.now() > autoPreferredUntil) {
    setAutoLanguagePreference(inferred, true);
    return;
  }
  if (inferred === autoPreferredLang) {
    autoPreferredUntil = Date.now() + AUTO_PREFERRED_MS;
    autoOppositeStreak = 0;
    return;
  }
  autoOppositeStreak += 1;
  if (autoOppositeStreak >= AUTO_SWITCH_STREAK) setAutoLanguagePreference(inferred, true);
}

function shouldSuppressPartial(text, detectedLang, selectedLang) {
  if (selectedLang === "ja") return detectedLang === "en" || looksEnglish(text);
  if (selectedLang === "en") return detectedLang === "ja" || looksJapanese(text);
  if (selectedLang !== "auto") return false;
  if (!autoPreferredLang || Date.now() > autoPreferredUntil) return false;
  const inferred = inferLanguage(text, detectedLang);
  return inferred && inferred !== autoPreferredLang;
}

function shouldSuppressFinal(text, detectedLang, selectedLang) {
  if (selectedLang === "ja") return detectedLang === "en" || looksEnglish(text);
  if (selectedLang === "en") return detectedLang === "ja" || looksJapanese(text);
  return false;
}

// ---------------------------------------------------------------------------
// Shared WebSocket message handler (used by both mic and viewer modes)
// ---------------------------------------------------------------------------

function handleWsMessage(event) {
  try {
    const msg = JSON.parse(event.data);
    if (msg.type === "partial") {
      if (!shouldSuppressPartial(msg.text || "", msg.lang || "", languageSelect.value)) {
        updatePartial(msg.text || "");
      }
    } else if (msg.type === "final") {
      addFinalEntry(msg.text || "", msg.lang || "");
    } else if (msg.type === "status") {
      // Suppress routine internal messages (model ready, language change, etc.)
      const m = msg.message || "";
      const isNoise = /^(Remote ready|Language set to|CUDA)/i.test(m);
      if (!isNoise) { clearPartial(); addStatusLine(m); }
    } else if (msg.type === "error") {
      clearPartial();
      addErrorLine(`Error: ${msg.message}`);
    }
  } catch {
    addStatusLine(String(event.data));
  }
}

// ---------------------------------------------------------------------------
// Viewer mode — auto-connects to /ws/view, no mic
// ---------------------------------------------------------------------------

function wsViewUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/view`;
}

function connectViewerSocket() {
  if (ws && ws.readyState <= 1) return;
  ws = new WebSocket(wsViewUrl());
  ws.onopen  = () => addStatusLine("[status] Connected to transcript feed");
  ws.onclose = () => {
    addStatusLine("[status] Disconnected — reconnecting in 3 s…");
    setTimeout(connectViewerSocket, 3000);
  };
  ws.onerror = () => {};
  ws.onmessage = handleWsMessage;
}

// ---------------------------------------------------------------------------
// Mic mode — teacher
// ---------------------------------------------------------------------------

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

async function connectSocket() {
  if (ws && ws.readyState <= 1) return;
  ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";

  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  ws.onclose = () => {
    if (isRunning) {
      clearPartial();
      addStatusLine("[status] Connection dropped — reconnecting…");
      micButton.className = "btn btn-mic mic-on";
      // Reconnect the WebSocket without stopping the mic stream
      setTimeout(async () => {
        try {
          ws = null;
          await connectSocket();
          addStatusLine("[status] Reconnected.");
        } catch (e) {
          addErrorLine(`Reconnect failed — stopping mic: ${e}`);
          stopMic();
        }
      }, 1500);
    }
  };
  ws.onmessage = handleWsMessage;

  if (languageSelect.value === "auto") resetAutoLanguageLock();
  pushLanguageConfig(languageSelect.value);
  micButton.className = "btn btn-mic mic-on";
}

async function startMic() {
  partialEl = null;
  lastFinalText = "";
  resetAutoLanguageLock();
  await connectSocket();

  const deviceId = micDeviceSelect.value;
  const audioConstraints = {
    channelCount: 1, noiseSuppression: true, echoCancellation: true, autoGainControl: true,
    ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
  };
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
  await populateMicDevices();

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/static/pcm-worklet.js");

  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, "pcm-recorder", {
    processorOptions: { targetSampleRate: 16000, chunkMillis: 200 },
  });

  workletNode.port.onmessage = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
  };

  sourceNode.connect(workletNode);
  workletNode.connect(audioContext.destination);

  isRunning = true;
  micButton.textContent = "Stop Mic";
  micButton.className = "btn btn-mic mic-on";
}

function stopMic() {
  isRunning = false;
  resetAutoLanguageLock();
  clearPartial();
  workletNode?.disconnect(); workletNode = null;
  sourceNode?.disconnect();  sourceNode  = null;
  mediaStream?.getTracks().forEach((t) => t.stop()); mediaStream = null;
  audioContext?.close(); audioContext = null;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
    ws.close();
  }
  micButton.textContent = "Start Mic";
  micButton.className = "btn btn-mic mic-off";
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

if (isViewer) {
  // Hide mic controls; auto-connect
  micButton.style.display      = "none";
  micDeviceSelect.style.display = "none";
  document.querySelector(".brand-en").textContent = "Seminar Assistant — Viewer";
  connectViewerSocket();
  resetAutoLanguageLock();
} else {
  populateMicDevices();

  micButton.addEventListener("click", async () => {
    if (!isRunning) {
      try { await startMic(); }
      catch (err) {
        const msg = !navigator.mediaDevices
          ? "Microphone not available — open this page at http://localhost:8088 (not the LAN IP) to use the mic."
          : `Could not start microphone: ${err}`;
        addErrorLine(msg);
        stopMic();
      }
    } else {
      stopMic();
    }
  });

  // Auto-start mic on page load (silently skip if permission not yet granted)
  startMic().catch(() => {});
}

languageSelect.addEventListener("change", () => {
  if (languageSelect.value === "auto") resetAutoLanguageLock();
  if (ws && ws.readyState === WebSocket.OPEN) pushLanguageConfig(languageSelect.value);
});

micDeviceSelect.addEventListener("change", saveMicPreference);

// ---------------------------------------------------------------------------
// Q&A panel
// ---------------------------------------------------------------------------

function addQaMessage(text, role) {
  const el = document.createElement("div");
  el.className = `qa-msg ${role}`;
  el.textContent = text;
  qaMessages.appendChild(el);
  qaMessages.scrollTop = qaMessages.scrollHeight;
  return el;
}

async function sendQuestion() {
  const q = qaInput.value.trim();
  if (!q) return;
  qaInput.value = "";
  qaSend.disabled = true;
  addQaMessage(q, "user");
  const loadingEl = addQaMessage("Thinking…", "bot loading");
  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const data = await resp.json();
    loadingEl.className = "qa-msg bot";
    loadingEl.textContent = data.answer || "(no answer)";
  } catch (err) {
    loadingEl.className = "qa-msg bot";
    loadingEl.textContent = `Error: ${err}`;
  } finally {
    qaSend.disabled = false;
    qaInput.focus();
  }
}

qaSend.addEventListener("click", sendQuestion);
qaInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
});
