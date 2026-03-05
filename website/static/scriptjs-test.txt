let audioQueue = [];
let isPlaying = false;

let socket;
let audioContext;
let processor;
let input;

/* =======================
   🔊 AUDIO PLAYBACK
======================= */
startInterview
function playAudio(arrayBuffer) {
  if (!arrayBuffer || arrayBuffer.byteLength === 0) return;

  audioQueue.push(arrayBuffer);
  if (!isPlaying) playNextChunk();
}

function playNextChunk() {
  if (audioQueue.length === 0) {
    isPlaying = false;
    return;
  }

  isPlaying = true;

  const buffer = audioQueue.shift();
  const pcm16 = new Int16Array(buffer);

  // ✅ FIX: ACTUALLY STORE audioBuffer
  const audioBuffer = audioContext.createBuffer(
    1,
    pcm16.length,
    48000
  );

  const channelData = audioBuffer.getChannelData(0);
  for (let i = 0; i < pcm16.length; i++) {
    channelData[i] = pcm16[i] / 32768;
  }

  const source = audioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(audioContext.destination);

  source.onended = () => {
    playNextChunk(); // 🔑 allows conversation to continue
  };

  source.start();
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
  document.getElementById("start").addEventListener("click", startInterview);
  document.getElementById("stop").addEventListener("click",stopInterview);
});

async function startInterview() {
  console.log("Start interview clicked");

  // 🔥 FIX: Automatically use correct protocol + host
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws`;

  console.log("Connecting to:", wsUrl);

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
          autoGainControl: true,
        },
      });

      input = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(2048, 1, 1);
      input.connect(processor);

      // Silent sink (prevents echo loop)
      const zeroGain = audioContext.createGain();
      zeroGain.gain.value = 0;
      processor.connect(zeroGain);
      zeroGain.connect(audioContext.destination);

      let silenceFrames = 0;
      const SILENCE_THRESHOLD = 0.002;
      const MAX_SILENCE_FRAMES = 15;
      let speaking = false;

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);

        let energy = 0;
        for (let i = 0; i < inputData.length; i++) {
          energy += Math.abs(inputData[i]);
        }

        if (energy > SILENCE_THRESHOLD) {
          speaking = true;
          silenceFrames = 0;

          const pcm16 = floatTo16BitPCM(inputData);
          socket.send(pcm16);
          return;
        }

        if (speaking) {
          silenceFrames++;

          if (silenceFrames > MAX_SILENCE_FRAMES) {
            socket.send(JSON.stringify({ type: "InputAudioEnd" }));
            speaking = false;
            silenceFrames = 0;
          }
        }
      };

    } catch (err) {
      console.error("Microphone access denied or failed:", err);
      alert("Microphone permission is required.");
    }
  };

  socket.onmessage = (event) => {
    if (typeof event.data === "string") {
      console.log("Transcript:", event.data);
      document.getElementById("output").textContent += event.data + "\n";
    } else {
      playAudio(event.data);
    }
  };

  socket.onerror = (e) => {
    console.error("WebSocket error:", e);
  };

  socket.onclose = () => {
    console.log("WebSocket closed");
  };
}
async function stopInterview() {
  console.log("Stopping interview...");

  if (!socket || socket.readyState !== WebSocket.OPEN) {
    console.log("No active socket.");
    return;
  }

  // 🔴 Tell backend to save transcript
  socket.send("STOP_INTERVIEW");

  // Stop mic capture
  if (processor) {
    processor.disconnect();
    processor.onaudioprocess = null;
  }

  if (input) {
    input.disconnect();
  }

  // Close audio context
  if (audioContext) {
    await audioContext.close();
  }

  // Clear audio playback queue
  audioQueue = [];
  isPlaying = false;

  // Close socket after slight delay
  setTimeout(() => {
    socket.close();
  }, 300);
}