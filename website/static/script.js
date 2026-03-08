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
  if (audioQueue.length === 0) {
    isPlaying = false;
    return;
  }

  isPlaying = true;

  const buffer = audioQueue.shift();
  const pcm16 = new Int16Array(buffer);

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

  source.onended = () => playNextChunk();

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
  document.getElementById("stop").addEventListener("click", stopInterview);
});

async function startInterview() {

  console.log("Start interview clicked");

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

        /* ✅ ALWAYS SEND AUDIO */
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(pcm16);
        }

        /* RMS energy */
        let sum = 0;
        for (let i = 0; i < inputData.length; i++) {
          sum += inputData[i] * inputData[i];
        }

        const energy = Math.sqrt(sum / inputData.length);

        if (energy > SILENCE_THRESHOLD) {

          speechFrames++;

          if (speechFrames > 3) {
            speaking = true;
          }

          silenceFrames = 0;

        } else {

          speechFrames = 0;

          if (speaking) {
            silenceFrames++;
          }

        }

        /* Detect end of speech */

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

      const output = document.getElementById("output");
      if (output) {
        output.textContent += event.data + "\n";
      }

    } else {

      playAudio(event.data);

    }

  };

  socket.onerror = (e) => {
    console.error("WebSocket error:", e);
  };

  socket.onclose = (event) => {
    console.log("WebSocket closed:", event.code, event.reason);
  };

}

/* =======================
   🛑 STOP INTERVIEW
======================= */

async function stopInterview() {

  console.log("Stopping interview...");

  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }

  socket.send("STOP_INTERVIEW");

  if (processor) {
    processor.disconnect();
    processor.onaudioprocess = null;
  }

  if (input) {
    input.disconnect();
  }

  if (audioContext) {
    await audioContext.close();
  }

  audioQueue = [];
  isPlaying = false;

  setTimeout(() => {
    socket.close();
  }, 300);

}