window.onerror = function(msg, url, line, col, error) {
    console.error("GLOBAL ERROR:", msg, "at line", line);
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
  
  // Reset UI state
  window.setAvatarState('listening');

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws`;

  socket = new WebSocket(wsUrl);
  socket.binaryType = "arraybuffer";

  socket.onopen = async () => {
    console.log("WebSocket connected");
    audioContext = new AudioContext({ sampleRate: 48000 });
    await audioContext.resume();

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
        if (socket && socket.readyState === WebSocket.OPEN) {
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
          if (socket && socket.readyState === WebSocket.OPEN) {
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
        console.log("Transcript:", event.data);

        try {
            const data = JSON.parse(event.data);

            if (data.type === "ConversationText" && data.role === "assistant") {
                window.setAvatarState('talking');
            }

        } catch (e) {}
    }else {
      console.log("Audio chunk received");
      playAudio(event.data);
    }
  };

  socket.onerror = (e) => console.error("WebSocket error:", e);
  socket.onclose = () => window.setAvatarState('idle');
}

/* =======================
    🛑 STOP INTERVIEW
======================= */

async function stopInterview() {
  console.log("Stopping interview...");
  window.setAvatarState('idle');

  if (!socket || socket.readyState !== WebSocket.OPEN) return;

  socket.send("STOP_INTERVIEW");

  if (processor) {
    processor.disconnect();
    processor.onaudioprocess = null;
  }
  if (input) input.disconnect();
  if (audioContext) await audioContext.close();

  audioQueue = [];
  isPlaying = false;

  setTimeout(() => { socket.close(); }, 300);
}