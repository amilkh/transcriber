const micButton = document.getElementById("micButton");
const transcript = document.getElementById("transcript");
const languageSelect = document.getElementById("language");
const connectionBadge = document.getElementById("connection");
const recordingBadge = document.getElementById("recording");

let ws;
let audioContext;
let mediaStream;
let sourceNode;
let workletNode;
let isRunning = false;

function appendLine(text) {
  const line = document.createElement("div");
  line.className = "line";
  line.textContent = text;
  transcript.appendChild(line);
  transcript.scrollTop = transcript.scrollHeight;
}

function setConnected(connected) {
  connectionBadge.textContent = connected ? "Connected" : "Disconnected";
}

function setRecording(on) {
  recordingBadge.textContent = on ? "Mic On" : "Mic Off";
}

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}

async function connectSocket() {
  if (ws && ws.readyState <= 1) {
    return;
  }

  ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  ws.onclose = () => {
    setConnected(false);
    if (isRunning) {
      appendLine("Connection closed.");
      stopMic();
    }
  };

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "partial" || payload.type === "final") {
        appendLine(payload.text);
      } else if (payload.type === "error") {
        appendLine(`Error: ${payload.message}`);
      }
    } catch {
      appendLine(String(event.data));
    }
  };

  ws.send(
    JSON.stringify({
      type: "config",
      language: languageSelect.value,
    })
  );

  setConnected(true);
}

async function startMic() {
  await connectSocket();

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      noiseSuppression: true,
      echoCancellation: true,
      autoGainControl: true,
    },
  });

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/static/pcm-worklet.js");

  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, "pcm-recorder", {
    processorOptions: {
      targetSampleRate: 16000,
      chunkMillis: 200,
    },
  });

  workletNode.port.onmessage = (event) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    ws.send(event.data);
  };

  sourceNode.connect(workletNode);
  workletNode.connect(audioContext.destination);

  isRunning = true;
  micButton.textContent = "Stop Mic";
  micButton.classList.remove("mic-off");
  micButton.classList.add("mic-on");
  setRecording(true);
}

function stopMic() {
  isRunning = false;

  if (workletNode) {
    workletNode.disconnect();
    workletNode = null;
  }

  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }

  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
    ws.close();
  }

  micButton.textContent = "Start Mic";
  micButton.classList.remove("mic-on");
  micButton.classList.add("mic-off");
  setRecording(false);
  setConnected(false);
}

micButton.addEventListener("click", async () => {
  if (!isRunning) {
    try {
      await startMic();
    } catch (err) {
      appendLine(`Could not start microphone: ${err}`);
      stopMic();
    }
    return;
  }

  stopMic();
});
