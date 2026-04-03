window.onerror = function(msg, url, line, col, error) {
    alert("JS Error: "+msg);
};

/* =======================
    🎨 ANIMATION MANAGER
======================= */

// Define globally at the top of the file
window.setAvatarState = function(state) {
    const box = document.querySelector('.avatar-container');

    if (!box) {
        console.error("Avatar container not found");
        return;
    }

    console.log("STATE:", state);

    box.classList.remove('is-talking', 'is-listening', 'is-idle');

    if (state === 'talking') {
        box.classList.add('is-talking');
    } else if (state === 'listening') {
        box.classList.add('is-listening');
    } else {
        box.classList.add('is-idle');
    }
};

let audioQueue = [];
let isPlaying = false;

let socket;
let audioContext;
let processor;
let input;


/* =======================
    🔊 AUDIO PLAYBACK
======================= */

function playAudio(arrayBuffer) {
    if (!arrayBuffer || arrayBuffer.byteLength === 0) return;
    audioQueue.push(arrayBuffer);
    if (!isPlaying) playNextChunk();
}

function playNextChunk() {
    if (!audioContext) {
        console.error("AudioContext not initialized");
        return;
    }

    if (audioQueue.length === 0) {
        isPlaying = false;
        window.setAvatarState('listening');
        return;
    }

    isPlaying = true;
    window.setAvatarState('talking');

    const buffer = audioQueue.shift();
    const pcm16 = new Int16Array(buffer);

    try {
        const audioBuffer = audioContext.createBuffer(1, pcm16.length, 48000);
        const channelData = audioBuffer.getChannelData(0);

        for (let i = 0; i < pcm16.length; i++) {
            channelData[i] = pcm16[i] / 32768;
        }

        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);

        source.onended = () => playNextChunk();
        source.start();

    } catch (err) {
        console.error("Audio playback error:", err);
    }
}
/* =======================
    🎙️ AUDIO CAPTURE
======================= */

function floatTo16BitPCM(float32) {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s * 0x7fff, true);
  }
  return buffer;
}

/* =======================
    🚀 MAIN
======================= */

window.addEventListener("DOMContentLoaded", () => {
  window.setAvatarState('idle');
  console.log("INARA Dashboard Ready");
  
  const startBtn = document.getElementById("start");
  const stopBtn = document.getElementById("stop");

  if (startBtn) startBtn.addEventListener("click", startInterview);
  if (stopBtn) stopBtn.addEventListener("click", stopInterview);
});

async function startInterview() {
  console.log("Start interview clicked");

  window.setAvatarState('listening');

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws`;

  socket = new WebSocket(wsUrl);
  socket.binaryType = "arraybuffer";

  socket.onopen = async () => {
    console.log("WebSocket connected");

    // 🎯 INIT AUDIO CONTEXT
    audioContext = new AudioContext({ sampleRate: 48000 });
    await audioContext.resume();

    // 🎯 SEND ROLE (FIXED)
    const role = localStorage.getItem("selected_role") || "web_developer";

    socket.send(JSON.stringify({
      type: "ROLE",
      role: role
    }));

    // 🎯 UNLOCK AUDIO (mobile fix)
    const dummy = audioContext.createBuffer(1, 1, 22050);
    const source = audioContext.createBufferSource();
    source.buffer = dummy;
    source.connect(audioContext.destination);
    source.start();

    // 🎯 MIC ACCESS
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      input = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);

      input.connect(processor);

      const zeroGain = audioContext.createGain();
      zeroGain.gain.value = 0;

      processor.connect(zeroGain);
      zeroGain.connect(audioContext.destination);

      let silenceFrames = 0;
      let speechFrames = 0;
      let speaking = false;

      const SILENCE_THRESHOLD = 0.002;
      const MAX_SILENCE_FRAMES = 60;

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        if (!inputData || inputData.length === 0) return;

        const pcm16 = floatTo16BitPCM(inputData);

        if (socket.readyState === WebSocket.OPEN) {
          socket.send(pcm16);
        }

        let sum = 0;
        for (let i = 0; i < inputData.length; i++) {
          sum += inputData[i] * inputData[i];
        }
        const energy = Math.sqrt(sum / inputData.length);

        if (energy > SILENCE_THRESHOLD) {
          window.setAvatarState('listening');
          speechFrames++;
          if (speechFrames > 3) speaking = true;
          silenceFrames = 0;
        } else {
          speechFrames = 0;
          if (speaking) silenceFrames++;
        }

        if (speaking && silenceFrames > MAX_SILENCE_FRAMES) {
          console.log("Speech ended");

          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "InputAudioEnd" }));
          }

          speaking = false;
          silenceFrames = 0;
          speechFrames = 0;
        }
      };

    } catch (err) {
      console.error("Microphone access failed:", err);
      alert("Microphone permission is required.");
    }
  };

  socket.onmessage = (event) => {

    if (typeof event.data === "string") {

        try {
            const data = JSON.parse(event.data);

            // ✅ Handle END INTERVIEW
            if (data.type === "END_INTERVIEW") {
              console.log("Interview ending — waiting for closing message to finish...");

              // ✅ Stop sending mic audio immediately
              if (processor) {
                  processor.disconnect();
                  processor.onaudioprocess = null;
              }
              if (input) input.disconnect();

              // ✅ Poll until Deepgram finishes speaking the closing message
              const checkDone = setInterval(() => {
                  if (!isPlaying && audioQueue.length === 0) {
                      clearInterval(checkDone);

                      if (audioContext && audioContext.state !== "closed") {
                          audioContext.close();
                      }

                      audioQueue = [];
                      isPlaying = false;
                      window.setAvatarState('idle');

                      setTimeout(() => { window.location.href = "/evaluation"; }, 600);
                  }
              }, 300);

              return;
          }
            // Normal conversation
            if (data.type === "ConversationText" && data.role === "assistant") {
                window.setAvatarState('talking');
            }

        } catch (e) {
            console.log("Non-JSON text:", event.data);
        }

    } else {
        playAudio(event.data);
    }
};

  socket.onerror = (e) => console.error("WebSocket error:", e);

  socket.onclose = () => {
    console.log("WebSocket closed");
    window.setAvatarState('idle');
  };
}
/* =======================
    🛑 STOP INTERVIEW
======================= */

async function stopInterview() {
    console.log("Stop button clicked");
    window.setAvatarState('idle');

    // If socket is already closed (e.g. called from END_INTERVIEW handler), just navigate
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        setTimeout(() => { window.location.href = "/evaluation"; }, 600);
        return;
    }

    // Send signal to backend — it will inject the closing message,
    // save the transcript, then reply with END_INTERVIEW
    socket.send("STOP_INTERVIEW");

    // ⚠️ Don't tear down audio or navigate here.
    // The END_INTERVIEW handler in socket.onmessage takes over from here,
    // waits for the closing message audio to finish, then navigates.
}


const cursor = document.querySelector('.neon-cursor');
const glow = document.querySelector('.neon-cursor-glow');

let mouseX = 0;
let mouseY = 0;

let glowX = 0;
let glowY = 0;

// Track mouse
document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;

    cursor.style.left = mouseX + 'px';
    cursor.style.top = mouseY + 'px';
});

// Smooth trailing effect
function animateGlow() {
    glowX += (mouseX - glowX) * 0.15;
    glowY += (mouseY - glowY) * 0.15;

    glow.style.left = glowX + 'px';
    glow.style.top = glowY + 'px';

    requestAnimationFrame(animateGlow);
}

animateGlow();

document.addEventListener("DOMContentLoaded", () => {

    const elements = document.querySelectorAll('.letter-hover');

    elements.forEach(el => {
        const text = el.textContent;
        el.innerHTML = '';

        text.split('').forEach((char, index) => {
            const span = document.createElement('span');
            span.textContent = char;

            // Preserve spaces
            if (char === ' ') {
                span.innerHTML = '&nbsp;';
            }

            span.style.transitionDelay = `${index * 0.03}s`;

            el.appendChild(span);
        });
    });

});
document.querySelectorAll(".role-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const role = btn.getAttribute("data-role");

    
    localStorage.setItem("selected_role", role);

    alert("Role selected: " + role);
  });
});
// Highlight current page in navbar
document.querySelectorAll(".nav-link-item").forEach(link => {
    if (link.getAttribute("href") === window.location.pathname) {
        link.classList.add("active");
    }
});