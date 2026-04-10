const micButton = document.getElementById("micButton");
const transcript = document.getElementById("transcript");
const languageSelect = document.getElementById("language");
const connectionBadge = document.getElementById("connection");
const recordingBadge = document.getElementById("recording");
const qaMessages = document.getElementById("qa-messages");
const qaInput = document.getElementById("qa-input");
const qaSend = document.getElementById("qa-send");

let ws;
let audioContext;
let mediaStream;
let sourceNode;
let workletNode;
let isRunning = false;
let partialEl = null;
let lastFinalText = "";
let autoLockedLang = "";
let autoLockUntil = 0;
let autoOppositeStreak = 0;

const AUTO_LOCK_MS = 12000;
const AUTO_SWITCH_STREAK = 2;

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
  partialEl.textContent = text;
  transcript.scrollTop = transcript.scrollHeight;
}

function addFinalEntry(text, detectedLang) {
  if (!text || text === lastFinalText) return;
  const selectedLang = languageSelect.value;
  if (selectedLang === "auto") {
    updateAutoLanguageLock(text, detectedLang);
  }
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

  // In Japanese mode, always show an English line from the translator.
  // In auto/English mode, only translate when the text appears Japanese.
  const shouldTranslate = selectedLang === "ja" ||
    detectedLang === "ja" ||
    (selectedLang === "auto" && looksJapanese(text));
  if (!shouldTranslate) return;

  const enEl = document.createElement("div");
  enEl.className = "entry-en loading";
  enEl.textContent = "translating…";
  entry.appendChild(enEl);

  fetch("/api/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .then((r) => r.json())
    .then((data) => {
      const t = data.translation || "";
      if (t) {
        enEl.className = "entry-en";
        enEl.textContent = t;
      } else {
        enEl.remove();
      }
    })
    .catch(() => enEl.remove());
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
  if (looksEnglish(text)) return "en";
  return "";
}

function languageLabel(lang) {
  return lang === "ja" ? "Japanese" : "English";
}

function resetAutoLanguageLock() {
  autoLockedLang = "";
  autoLockUntil = 0;
  autoOppositeStreak = 0;
}

function pushLanguageConfig(lang) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "config", language: lang }));
  }
}

function lockAutoLanguage(nextLang, announce) {
  autoLockedLang = nextLang;
  autoLockUntil = Date.now() + AUTO_LOCK_MS;
  autoOppositeStreak = 0;
  pushLanguageConfig(nextLang);
  if (announce) {
    addStatusLine(`[status] Auto locked to ${languageLabel(nextLang)}`);
  }
}

function updateAutoLanguageLock(text, detectedLang) {
  const inferred = inferLanguage(text, detectedLang);
  if (!inferred) return;

  if (!autoLockedLang || Date.now() > autoLockUntil) {
    lockAutoLanguage(inferred, true);
    return;
  }

  if (inferred === autoLockedLang) {
    autoLockUntil = Date.now() + AUTO_LOCK_MS;
    autoOppositeStreak = 0;
    return;
  }

  autoOppositeStreak += 1;
  if (autoOppositeStreak >= AUTO_SWITCH_STREAK) {
    lockAutoLanguage(inferred, true);
  }
}

function shouldSuppressPartial(text, detectedLang, selectedLang) {
  if (selectedLang === "ja") return detectedLang === "en" || looksEnglish(text);
  if (selectedLang === "en") return detectedLang === "ja" || looksJapanese(text);
  if (selectedLang !== "auto") return false;
  if (!autoLockedLang) return false;
  const inferred = inferLanguage(text, detectedLang);
  return inferred && inferred !== autoLockedLang;
}

function shouldSuppressFinal(text, detectedLang, selectedLang) {
  // If user selected Japanese, hide English-only hypotheses from bilingual auto behavior.
  if (selectedLang === "ja") return detectedLang === "en" || looksEnglish(text);
  if (selectedLang === "en") return detectedLang === "ja" || looksJapanese(text);
  if (selectedLang !== "auto") return false;
  if (!autoLockedLang) return false;
  const inferred = inferLanguage(text, detectedLang);
  return inferred && inferred !== autoLockedLang;
}

// ---------------------------------------------------------------------------
// WebSocket connection & mic
// ---------------------------------------------------------------------------

function setConnected(on) {
  connectionBadge.textContent = on ? "Connected" : "Disconnected";
  connectionBadge.className = `badge ${on ? "badge-on" : "badge-off"}`;
}

function setRecording(on) {
  recordingBadge.textContent = on ? "Mic On" : "Mic Off";
  recordingBadge.className = `badge ${on ? "badge-on" : "badge-off"}`;
}

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
    setConnected(false);
    if (isRunning) { clearPartial(); addStatusLine("Connection closed."); stopMic(); }
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "partial") {
        if (!shouldSuppressPartial(msg.text || "", msg.lang || "", languageSelect.value)) {
          updatePartial(msg.text || "");
        }
      } else if (msg.type === "final") {
        addFinalEntry(msg.text || "", msg.lang || "");
      } else if (msg.type === "status") {
        clearPartial();
        addStatusLine(`[status] ${msg.message}`);
      } else if (msg.type === "error") {
        clearPartial();
        addErrorLine(`Error: ${msg.message}`);
      }
    } catch {
      addStatusLine(String(event.data));
    }
  };

  if (languageSelect.value === "auto") {
    resetAutoLanguageLock();
  }
  pushLanguageConfig(languageSelect.value);
  setConnected(true);
}

async function startMic() {
  partialEl = null;
  lastFinalText = "";
  resetAutoLanguageLock();
  await connectSocket();

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, noiseSuppression: true, echoCancellation: true, autoGainControl: true },
  });

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
  setRecording(true);
}

function stopMic() {
  isRunning = false;
  resetAutoLanguageLock();
  clearPartial();
  workletNode?.disconnect(); workletNode = null;
  sourceNode?.disconnect();  sourceNode = null;
  mediaStream?.getTracks().forEach((t) => t.stop()); mediaStream = null;
  audioContext?.close(); audioContext = null;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
    ws.close();
  }
  micButton.textContent = "Start Mic";
  micButton.className = "btn btn-mic mic-off";
  setRecording(false);
  setConnected(false);
}

micButton.addEventListener("click", async () => {
  if (!isRunning) {
    try { await startMic(); }
    catch (err) { addErrorLine(`Could not start microphone: ${err}`); stopMic(); }
  } else {
    stopMic();
  }
});

languageSelect.addEventListener("change", () => {
  if (languageSelect.value === "auto") {
    resetAutoLanguageLock();
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    pushLanguageConfig(languageSelect.value);
  }
});

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
