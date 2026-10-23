let ws = null;
let audioContext = null;
let micStream = null;
let scriptProcessor = null;
let playbackAudioContext = null;
let nextPlaybackTime = 0;
let callStartTime = null;
let timerInterval = null;
let isCallActive = false;

// UI Elements
const liveDot = document.getElementById("liveDot");
const callStatusText = document.getElementById("callStatusText");
const callTimer = document.getElementById("callTimer");
const levelTag = document.getElementById("levelTag");
const levelSelect = document.getElementById("levelSelect");
const levelTitleText = document.getElementById("levelTitleText");
const levelPassText = document.getElementById("levelPassText");
const levelProgressFill = document.getElementById("levelProgressFill");
const pulseRing = document.getElementById("pulseRing");
const characterDesc = document.getElementById("characterDesc");
const aiText = document.getElementById("aiText");
const userText = document.getElementById("userText");
const userSubtitle = document.getElementById("userSubtitle");
const subtitlesBox = document.getElementById("subtitlesBox");
const sosBtn = document.getElementById("sosBtn");
const startCallBtn = document.getElementById("startCallBtn");
const endCallBtn = document.getElementById("endCallBtn");
const callingArea = document.getElementById("callingArea");
const feedbackArea = document.getElementById("feedbackArea");
const feedbackContent = document.getElementById("feedbackContent");
const retryBtn = document.getElementById("retryBtn");
const openLogsFolderBtn = document.getElementById("openLogsFolderBtn");

// Load Profile on startup
async function loadProfile() {
  try {
    const res = await fetch("/api/profile");
    if (res.ok) {
      const data = await res.json();
      updateLevelUI(data);
    }
  } catch (e) {
    console.error("Failed to load profile:", e);
  }
}

function updateLevelUI(data) {
  const lvl = data.current_level || "N4";
  levelTag.textContent = `JLPT ${lvl}`;
  levelSelect.value = lvl;
  levelTitleText.textContent = data.title ? data.title.split("(")[1]?.replace(")", "") || data.title : "초급 회화 완성";
  levelPassText.textContent = `${data.pass_count}/${data.required_pass_count} 성공`;
  levelProgressFill.style.width = `${data.progress_percent || 0}%`;
}

levelSelect.addEventListener("change", async (e) => {
  const chosen = e.target.value;
  try {
    const res = await fetch("/api/set-level", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: chosen })
    });
    if (res.ok) {
      const data = await res.json();
      updateLevelUI(data);
    }
  } catch (err) {
    console.error("Failed to set level", err);
  }
});

loadProfile();

// 1. Start Call
startCallBtn.addEventListener("click", async () => {
  try {
    startCallBtn.disabled = true;
    callStatusText.textContent = "마이크 연결 중...";

    // Initialize Web Audio API for Playback (24kHz for Gemini Live)
    playbackAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    nextPlaybackTime = playbackAudioContext.currentTime;

    // Request Microphone access
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });

    // Initialize AudioContext for Microphone (16kHz for Gemini input)
    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(micStream);
    scriptProcessor = audioContext.createScriptProcessor(2048, 1, 1);

    // Connect WebSocket
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/call`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      isCallActive = true;
      callStartTime = Date.now();
      callStatusText.textContent = "통화 중";
      liveDot.classList.add("active");
      sosBtn.disabled = false;
      startCallBtn.style.display = "none";
      endCallBtn.style.display = "flex";
      startCallBtn.disabled = false;

      // Start 8-minute Timer
      startTimer();

      // Hook Microphone stream to WebSocket
      source.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);

      scriptProcessor.onaudioprocess = (e) => {
        if (!isCallActive || !ws || ws.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Convert Float32 to 16-bit PCM Little-Endian
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        ws.send(pcmData.buffer);
      };
    };

    ws.onmessage = (event) => {
      // 1. Binary Audio Chunk from Gemini (24kHz PCM)
      if (event.data instanceof ArrayBuffer) {
        playIncomingAudio(event.data);
      } else {
        // 2. JSON Event
        try {
          const data = JSON.parse(event.data);
          handleServerEvent(data);
        } catch (e) {
          console.error("JSON parse error", e);
        }
      }
    };

    ws.onclose = () => {
      endCallCleanup();
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      callStatusText.textContent = "연결 오류";
      endCallCleanup();
    };

  } catch (err) {
    alert("마이크 사용 권한이 필요합니다: " + err.message);
    callStatusText.textContent = "마이크 권한 필요";
    startCallBtn.disabled = false;
  }
});

// 2. Play Incoming 24kHz PCM Audio
function playIncomingAudio(arrayBuffer) {
  if (!playbackAudioContext || !isCallActive) return;

  const int16Array = new Int16Array(arrayBuffer);
  const float32Array = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32Array[i] = int16Array[i] / 32768.0;
  }

  const audioBuffer = playbackAudioContext.createBuffer(1, float32Array.length, 24000);
  audioBuffer.getChannelData(0).set(float32Array);

  const bufferSource = playbackAudioContext.createBufferSource();
  bufferSource.buffer = audioBuffer;
  bufferSource.connect(playbackAudioContext.destination);

  const now = playbackAudioContext.currentTime;
  if (nextPlaybackTime < now) {
    nextPlaybackTime = now;
  }
  bufferSource.start(nextPlaybackTime);
  nextPlaybackTime += audioBuffer.duration;

  // Pulse animation while playing
  setSpeakingState(true);
  bufferSource.onended = () => {
    if (playbackAudioContext && playbackAudioContext.currentTime >= nextPlaybackTime - 0.1) {
      setSpeakingState(false);
    }
  };
}

// 3. Handle Server JSON Events
function handleServerEvent(data) {
  if (data.type === "ai_transcript") {
    aiText.textContent = data.text;
    subtitlesBox.scrollTop = subtitlesBox.scrollHeight;
  } else if (data.type === "user_transcript") {
    userSubtitle.style.display = "flex";
    userText.textContent = data.text;
    subtitlesBox.scrollTop = subtitlesBox.scrollHeight;
  } else if (data.type === "interrupted") {
    nextPlaybackTime = playbackAudioContext ? playbackAudioContext.currentTime : 0;
    setSpeakingState(false);
  } else if (data.type === "stage_update") {
    updateStageUI(data.stage, data.title, data.level);
  } else if (data.type === "feedback_report") {
    showFeedbackReport(data.markdown);
    if (data.level_result) {
      if (data.level_result.leveled_up) {
        alert(`🎉 축하합니다! JLPT ${data.level_result.current_level}로 레벨업 하셨습니다! 다음 통화부터는 새로운 레벨에 맞춰 진행됩니다.`);
      }
      loadProfile();
    }
  }
}

// 4. UI State Updaters
function setSpeakingState(speaking) {
  if (speaking) {
    pulseRing.classList.add("speaking");
  } else {
    pulseRing.classList.remove("speaking");
  }
}

function updateStageUI(stageNum, stageTitle, levelDesc) {
  characterDesc.textContent = `${stageTitle} • ${levelDesc}`;

  // Update step indicators
  for (let i = 1; i <= 5; i++) {
    const stepEl = document.getElementById(`step${i}`);
    const lineEl = document.getElementById(`line${i}`);
    if (i <= stageNum) {
      stepEl.classList.add("active");
      if (lineEl && i < stageNum) lineEl.classList.add("active");
    } else {
      stepEl.classList.remove("active");
      if (lineEl) lineEl.classList.remove("active");
    }
  }
}

// 5. Timer
function startTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    if (!callStartTime) return;
    const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
    const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const s = String(elapsed % 60).padStart(2, "0");
    callTimer.textContent = `${m}:${s} / 08:00`;

    if (elapsed >= 480) { // 8 minutes
      endCall();
    }
  }, 1000);
}

// 6. SOS Button Click
sosBtn.addEventListener("click", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "sos" }));
    aiText.textContent = "한국어로 뜻과 예시를 설명하고 있어요... 잠시만 기다려주세요!";
  }
});

// 7. End Call
endCallBtn.addEventListener("click", () => {
  endCall();
});

function endCall() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "end" }));
  }
  endCallCleanup();
}

function endCallCleanup() {
  isCallActive = false;
  if (timerInterval) clearInterval(timerInterval);
  liveDot.classList.remove("active");
  callStatusText.textContent = "통화 종료됨";
  sosBtn.disabled = true;
  setSpeakingState(false);

  startCallBtn.style.display = "flex";
  endCallBtn.style.display = "none";

  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }
  if (scriptProcessor) {
    try { scriptProcessor.disconnect(); } catch (e) {}
    scriptProcessor = null;
  }
  if (audioContext && audioContext.state !== "closed") {
    audioContext.close();
  }
  if (playbackAudioContext && playbackAudioContext.state !== "closed") {
    playbackAudioContext.close();
  }

  // Switch to Feedback Area view
  callingArea.style.display = "none";
  feedbackArea.style.display = "flex";
}

// 8. Render Markdown Feedback
function showFeedbackReport(markdown) {
  if (!markdown) {
    feedbackContent.innerHTML = "<p>대화 내용이 짧아 리포트가 생성되지 않았습니다. 다시 대화해보세요!</p>";
    return;
  }
  // Simple markdown to HTML parser for headers, lists, and bold text
  let html = markdown
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/gim, '<em>$1</em>')
    .replace(/^\* (.*$)/gim, '<li>$1</li>')
    .replace(/^- (.*$)/gim, '<li>$1</li>')
    .replace(/\n\n/gim, '<br><br>');

  feedbackContent.innerHTML = html;
}

// 9. Retry Call Button
retryBtn.addEventListener("click", () => {
  feedbackArea.style.display = "none";
  callingArea.style.display = "flex";
  callStatusText.textContent = "대기 중";
  callTimer.textContent = "00:00 / 08:00";
  aiText.textContent = "아래 '전화 걸기' 버튼을 누르면 통화가 시작돼요!";
  userSubtitle.style.display = "none";
  updateStageUI(1, "일상 및 취미", "N5 기초 수준");
});

// 10. Open Logs Folder API
openLogsFolderBtn.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/open-logs", { method: "POST" });
    if (!res.ok) alert("폴더 열기에 실패했습니다.");
  } catch (e) {
    alert("오류 발생: " + e.message);
  }
});
