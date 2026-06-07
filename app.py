# frontend/app.py
# ============================================================
# Streamlit Frontend — Nemotron 3.5 ASR
# Captures browser microphone audio and streams it to the
# FastAPI backend via WebSocket.
# ============================================================

import streamlit as st
import requests
import json
import os
import tempfile
from pathlib import Path

# ── Backend URL resolution ────────────────────────────────
def get_backend_url() -> str:
    """
    Priority:
    1. Streamlit secrets  (production / Streamlit Cloud)
    2. BACKEND_URL env    (local docker / run.py)
    3. Meta file from run.py / ngrok
    4. localhost fallback
    """
    try:
        return st.secrets["backend"]["url"].rstrip("/")
    except Exception:
        pass

    env = os.environ.get("BACKEND_URL", "").rstrip("/")
    if env:
        return env

    meta = Path(tempfile.gettempdir()) / "stt_backend_url.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text())
            return data.get("http", "").rstrip("/")
        except Exception:
            pass

    return "http://localhost:8000"


BACKEND_URL = get_backend_url()
WS_URL      = BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws/stream"


# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="Nemotron 3.5 ASR — Arabic STT",
    page_icon="🎙️",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────
st.markdown("""
<style>
  .transcript-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    font-size: 1.15rem;
    line-height: 2;
    direction: rtl;
    text-align: right;
    min-height: 120px;
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
  }
  .partial-text { color: #8b949e; font-style: italic; }
  .final-text   { color: #e6edf3; }
  .metric-card  {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 0.8rem;
    text-align: center;
  }
  .status-dot-green { color: #3fb950; font-size: 0.8rem; }
  .status-dot-red   { color: #f85149; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ── WebSocket JS component ────────────────────────────────
WS_COMPONENT = f"""
<script>
(function() {{
  const WS_URL = "{WS_URL}";
  let socket, mediaRecorder, stream;
  let isRecording = false;

  function updateStatus(msg, ok, detail = "") {{
    const el = document.getElementById("ws-status");
    const debug = document.getElementById("ws-debug");
    if (el) {{
      el.textContent = msg;
      el.style.color = ok ? "#3fb950" : "#f85149";
    }}
    if (debug) {{
      debug.textContent = detail;
    }}
  }}

  function sendToStreamlit(data) {{
    window.parent.postMessage({{type: "streamlit:setComponentValue", value: data}}, "*");
  }}

  window.startRecording = async function() {{
    if (isRecording) return;
    try {{
      stream = await navigator.mediaDevices.getUserMedia({{
        audio: {{ sampleRate: 16000, channelCount: 1, echoCancellation: true }}
      }});

      updateStatus("● Connecting…", false, "Backend: " + WS_URL);
      socket = new WebSocket(WS_URL);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {{
        updateStatus("● Connected", true, "Backend: " + WS_URL);
        const audioCtx = new AudioContext({{ sampleRate: 16000 }});
        const source   = audioCtx.createMediaStreamSource(stream);
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);

        source.connect(processor);
        processor.connect(audioCtx.destination);

        processor.onaudioprocess = (e) => {{
          if (socket.readyState !== WebSocket.OPEN) return;
          const pcm = e.inputBuffer.getChannelData(0);
          socket.send(pcm.buffer.slice(0));
        }};

        isRecording = true;
      }};

      socket.onmessage = (e) => {{
        const msg = JSON.parse(e.data);
        if (msg.type === "partial" || msg.type === "final") {{
          sendToStreamlit(msg);
        }}
      }};

      socket.onerror  = () => updateStatus("● Connection error", false, "Check backend at: " + WS_URL);
      socket.onclose  = () => {{
        updateStatus("● Disconnected", false, "Backend: " + WS_URL);
        isRecording = false;
      }};

    }} catch(err) {{
      updateStatus("● Mic error: " + err.message, false, "Backend: " + WS_URL);
    }}
  }};

  window.stopRecording = function() {{
    if (socket) {{
      socket.send(JSON.stringify({{type: "stop"}}));
      socket.close();
    }}
    if (stream) stream.getTracks().forEach(t => t.stop());
    isRecording = false;
    updateStatus("● Stopped", false);
  }};
}})();
</script>
<div style="font-size:0.8rem; margin-top:4px; line-height:1.2;">
  <div><span id="ws-status" class="status-dot-red">● Not connected</span></div>
  <div id="ws-debug" style="color:#8b949e; font-size:0.75rem; margin-top:2px;">Backend: {WS_URL}</div>
</div>
"""

# ── Header ────────────────────────────────────────────────
st.title("🎙️ Nemotron 3.5 ASR")
st.caption("Cache-Aware FastConformer-RNNT · Arabic · Real-time Streaming")

# ── Backend health check ──────────────────────────────────
with st.spinner("Checking backend…"):
    try:
        r    = requests.get(f"{BACKEND_URL}/health", timeout=5)
        info = r.json()
        healthy = r.status_code == 200 and info.get("status") == "ok"
    except Exception:
        healthy = False
        info    = {}

if healthy:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Model",   info.get("model", "—").split("/")[-1])
    col2.metric("Language", info.get("target_lang", "—"))
    col3.metric("Preset",  info.get("latency_preset", "—"))
    col4.metric("Latency", f"~{info.get('approx_latency_ms', '?')}ms")
    st.success("Backend ready", icon="✅")
else:
    st.error(
        f"Backend not reachable at `{BACKEND_URL}`. "
        "Start the backend with `python run.py` or update the URL in secrets.",
        icon="❌",
    )

st.divider()

# ── Tabs ──────────────────────────────────────────────────
tab_mic, tab_file = st.tabs(["🎤 Microphone", "📂 File Upload"])

# ════════════════════════════════════════════════════════
# TAB 1 — MICROPHONE
# ════════════════════════════════════════════════════════
with tab_mic:
    st.markdown("**Live microphone transcription via WebSocket**")

    if not healthy:
        st.warning("Backend must be running to use microphone mode.")
    else:
        # Session state
        if "transcript" not in st.session_state:
            st.session_state.transcript = ""
        if "partial"    not in st.session_state:
            st.session_state.partial    = ""
        if "recording"  not in st.session_state:
            st.session_state.recording  = False

        col_start, col_stop, col_clear = st.columns([1, 1, 2])

        with col_start:
            if st.button("▶ Start", type="primary", disabled=st.session_state.recording):
                st.session_state.recording = True
                st.markdown(
                    "<script>window.startRecording();</script>",
                    unsafe_allow_html=True,
                )

        with col_stop:
            if st.button("⏹ Stop", disabled=not st.session_state.recording):
                st.session_state.recording = False
                st.markdown(
                    "<script>window.stopRecording();</script>",
                    unsafe_allow_html=True,
                )

        with col_clear:
            if st.button("🗑 Clear transcript"):
                st.session_state.transcript = ""
                st.session_state.partial    = ""

        # WebSocket JS bridge
        st.components.v1.html(WS_COMPONENT, height=30)

        # Transcript display
        st.markdown("#### Transcript")
        display_html = ""
        if st.session_state.transcript:
            display_html += (
                f'<span class="final-text">{st.session_state.transcript}</span> '
            )
        if st.session_state.partial:
            display_html += (
                f'<span class="partial-text">{st.session_state.partial}…</span>'
            )
        if not display_html:
            display_html = '<span style="color:#484f58;">Transcript will appear here…</span>'

        st.markdown(
            f'<div class="transcript-box">{display_html}</div>',
            unsafe_allow_html=True,
        )

        # Download
        if st.session_state.transcript:
            st.download_button(
                "⬇ Download transcript",
                data=st.session_state.transcript,
                file_name="transcript_ar.txt",
                mime="text/plain",
            )

# ════════════════════════════════════════════════════════
# TAB 2 — FILE UPLOAD
# ════════════════════════════════════════════════════════
with tab_file:
    st.markdown("**Upload an audio file for full transcription**")

    uploaded = st.file_uploader(
        "Choose audio file",
        type=["wav", "mp3", "flac", "ogg", "m4a", "webm", "opus"],
        help="Mono or stereo; will be resampled to 16 kHz automatically",
    )

    stream_mode = st.checkbox(
        "Streaming mode (show partial results)",
        value=True,
        help="Uses /transcribe endpoint with NDJSON streaming",
    )

    if uploaded and st.button("🚀 Transcribe", type="primary"):
        if not healthy:
            st.error("Backend not available.")
        else:
            progress   = st.progress(0, text="Uploading…")
            transcript_placeholder = st.empty()
            metrics_placeholder    = st.empty()

            full_text = ""
            segments  = []

            if stream_mode:
                # ── NDJSON streaming ──────────────────────
                with requests.post(
                    f"{BACKEND_URL}/transcribe",
                    files={"file": (uploaded.name, uploaded.getvalue())},
                    stream=True,
                    timeout=300,
                ) as resp:
                    if resp.status_code != 200:
                        st.error(f"Backend error {resp.status_code}")
                    else:
                        progress.progress(10, text="Transcribing…")
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                            except Exception:
                                continue

                            mtype = msg.get("type")
                            if mtype in ("partial", "final"):
                                full_text = msg.get("text", "")
                                transcript_placeholder.markdown(
                                    f'<div class="transcript-box">'
                                    f'<span class="{"partial-text" if mtype == "partial" else "final-text"}">'
                                    f'{full_text}</span></div>',
                                    unsafe_allow_html=True,
                                )
                                if mtype == "final":
                                    segments.append(msg)

                            elif mtype == "summary":
                                full_text = msg.get("text", full_text)
                                progress.progress(100, text="Done ✅")

            else:
                # ── Full JSON ─────────────────────────────
                progress.progress(20, text="Uploading…")
                resp = requests.post(
                    f"{BACKEND_URL}/transcribe/file",
                    files={"file": (uploaded.name, uploaded.getvalue())},
                    timeout=300,
                )
                progress.progress(100, text="Done ✅")

                if resp.status_code == 200:
                    data      = resp.json()
                    full_text = data.get("transcript", "")
                    segments  = data.get("events", [])

                    transcript_placeholder.markdown(
                        f'<div class="transcript-box">'
                        f'<span class="final-text">{full_text}</span></div>',
                        unsafe_allow_html=True,
                    )

                    stats = data.get("stats", {})
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Segments",      stats.get("segment_count", "—"))
                    c2.metric("Avg latency",   f"{stats.get('avg_segment_latency_ms', 0):.0f}ms")
                    c3.metric("Avg RTF",       f"{stats.get('avg_rtf', 0):.3f}")
                else:
                    st.error(f"Error {resp.status_code}: {resp.text}")

            # ── Download ──────────────────────────────────
            if full_text:
                st.download_button(
                    "⬇ Download transcript",
                    data=full_text,
                    file_name=f"{Path(uploaded.name).stem}_transcript.txt",
                    mime="text/plain",
                )

# ── Footer ────────────────────────────────────────────────
st.divider()
st.caption(
    f"Backend: `{BACKEND_URL}` · "
    "Model: nvidia/nemotron-3.5-asr-streaming-0.6b · "
    "NeMo 26.06+"
)
