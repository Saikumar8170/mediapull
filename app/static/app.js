(() => {
  const urlInput = document.getElementById("url-input");
  const pasteBtn = document.getElementById("paste-btn");
  const clearBtn = document.getElementById("clear-btn");
  const platformBadge = document.getElementById("platform-badge");
  const previewCard = document.getElementById("preview-card");
  const previewThumb = document.getElementById("preview-thumb");
  const previewTitle = document.getElementById("preview-title");
  const previewMeta = document.getElementById("preview-meta");

  const segBtns = document.querySelectorAll(".seg-btn");
  const qualityLabel = document.getElementById("quality-label");
  const qualityPills = document.getElementById("quality-pills");
  const form = document.getElementById("convert-form");
  const submitBtn = document.getElementById("submit-btn");
  const submitText = document.getElementById("submit-text");

  const pipelineBox = document.getElementById("pipeline-box");
  const progressFill = document.getElementById("progress-fill");
  const telemetryStatus = document.getElementById("telemetry-status");
  const telemetryStats = document.getElementById("telemetry-stats");
  const errorBox = document.getElementById("error-box");
  const readyBox = document.getElementById("ready-box");
  const readyFilename = document.getElementById("ready-filename");
  const readySize = document.getElementById("ready-size");
  const downloadLink = document.getElementById("download-link");

  const historyPanel = document.getElementById("history-panel");
  const historyList = document.getElementById("history-list");
  const clearHistoryBtn = document.getElementById("clear-history-btn");

  const DEFAULT_VIDEO_QUALITIES = ["1080p", "720p", "480p", "360p"];
  const AUDIO_QUALITIES = ["320k", "192k", "128k"];

  let state = {
    format: "mp4",
    videoQualities: [...DEFAULT_VIDEO_QUALITIES],
    quality: "1080p",
    probeTimer: null,
    activeSource: null,
  };

  function detectPlatformClient(raw) {
    try {
      const u = new URL(raw.trim());
      const h = u.hostname.toLowerCase();
      if (h.includes("youtube.com") || h === "youtu.be") return "youtube";
      if (h.includes("instagram.com") || h === "instagr.am") return "instagram";
    } catch (_) {}
    return "none";
  }

  function formatDuration(sec) {
    if (!sec) return "";
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    const h = Math.floor(m / 60);
    if (h > 0) {
      return `${h}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function formatBytes(bytes) {
    if (!bytes) return "";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function renderQualityPills() {
    const opts = state.format === "mp4" ? state.videoQualities : AUDIO_QUALITIES;
    qualityLabel.textContent = state.format === "mp4" ? "RESOLUTION" : "BITRATE";
    if (!opts.includes(state.quality)) {
      state.quality = opts[0];
    }
    qualityPills.innerHTML = "";
    opts.forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `pill-btn${opt === state.quality ? " active" : ""}`;
      btn.textContent = opt.toUpperCase();
      btn.addEventListener("click", () => {
        state.quality = opt;
        renderQualityPills();
      });
      qualityPills.appendChild(btn);
    });
  }

  function updatePlatformUI(url) {
    const p = detectPlatformClient(url);
    platformBadge.dataset.platform = p;
    platformBadge.textContent = p === "none" ? "WAITING" : p.toUpperCase();
    clearBtn.classList.toggle("hidden", !url.trim());
  }

  async function runProbe(url) {
    const p = detectPlatformClient(url);
    if (p === "none") {
      previewCard.classList.add("hidden");
      return;
    }
    try {
      const resp = await fetch("/api/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (urlInput.value.trim() !== url.trim()) return;

      previewTitle.textContent = data.title || "Media";
      const parts = [data.platform.toUpperCase()];
      if (data.uploader) parts.push(data.uploader);
      if (data.duration) parts.push(formatDuration(data.duration));
      previewMeta.textContent = parts.join(" · ");

      if (data.thumbnail) {
        previewThumb.src = data.thumbnail;
        previewThumb.classList.remove("hidden");
      } else {
        previewThumb.classList.add("hidden");
      }
      previewCard.classList.remove("hidden");

      if (Array.isArray(data.qualities) && data.qualities.length) {
        state.videoQualities = data.qualities;
        if (state.format === "mp4") renderQualityPills();
      }
    } catch (_) {}
  }

  function setStepHighlight(stage) {
    const order = ["queued", "downloading", "processing", "ready"];
    const mapped = stage === "fetching" ? "queued" : stage;
    const idx = order.indexOf(mapped);
    document.querySelectorAll(".p-step").forEach((el) => {
      const s = el.dataset.step;
      const sIdx = order.indexOf(s);
      el.classList.remove("active", "done");
      if (stage === "ready") {
        el.classList.add("done");
      } else if (sIdx < idx) {
        el.classList.add("done");
      } else if (sIdx === idx) {
        el.classList.add("active");
      }
    });
  }

  function saveHistory(item) {
    const raw = localStorage.getItem("mp_history");
    const list = raw ? JSON.parse(raw) : [];
    const filtered = list.filter((x) => x.job_id !== item.job_id);
    filtered.unshift(item);
    localStorage.setItem("mp_history", JSON.stringify(filtered.slice(0, 6)));
    renderHistory();
  }

  function renderHistory() {
    const raw = localStorage.getItem("mp_history");
    const list = raw ? JSON.parse(raw) : [];
    if (!list.length) {
      historyPanel.classList.add("hidden");
      return;
    }
    historyPanel.classList.remove("hidden");
    historyList.innerHTML = "";
    list.forEach((item) => {
      const li = document.createElement("li");
      li.className = "history-item";
      const title = document.createElement("span");
      title.className = "history-title";
      title.textContent = item.download_name || item.title || item.job_id;
      const a = document.createElement("a");
      a.className = "history-dl";
      a.href = item.download_url;
      a.textContent = item.format.toUpperCase();
      a.setAttribute("download", "");
      li.appendChild(title);
      li.appendChild(a);
      historyList.appendChild(li);
    });
  }

  function handleJobUpdate(data) {
    pipelineBox.classList.remove("hidden");
    setStepHighlight(data.stage);
    progressFill.style.width = `${data.percent || 0}%`;

    if (data.stage === "error") {
      telemetryStatus.textContent = "FAILED";
      telemetryStats.textContent = "";
      errorBox.textContent = data.error || "Conversion failed.";
      errorBox.classList.remove("hidden");
      readyBox.classList.add("hidden");
      submitBtn.disabled = false;
      submitText.textContent = "CONVERT";
      return;
    }

    errorBox.classList.add("hidden");

    if (data.stage === "ready") {
      telemetryStatus.textContent = "COMPLETE";
      telemetryStats.textContent = "100%";
      readyFilename.textContent = data.download_name;
      readySize.textContent = `${data.format.toUpperCase()} · ${formatBytes(data.file_size)}`;
      downloadLink.href = data.download_url;
      readyBox.classList.remove("hidden");
      submitBtn.disabled = false;
      submitText.textContent = "CONVERT";
      saveHistory({
        job_id: data.job_id,
        title: data.title,
        download_name: data.download_name,
        download_url: data.download_url,
        format: data.format,
      });
      return;
    }

    const stageLabels = {
      queued: "QUEUED",
      fetching: "READING STREAM",
      downloading: "DOWNLOADING",
      processing: "MUXING / TRANSCODING",
    };
    telemetryStatus.textContent = stageLabels[data.stage] || data.stage.toUpperCase();
    const statParts = [`${(data.percent || 0).toFixed(1)}%`];
    if (data.speed) statParts.push(data.speed);
    if (data.eta) statParts.push(`ETA ${data.eta}`);
    telemetryStats.textContent = statParts.join(" · ");
  }

  urlInput.addEventListener("input", () => {
    const val = urlInput.value.trim();
    updatePlatformUI(val);
    clearTimeout(state.probeTimer);
    state.probeTimer = setTimeout(() => runProbe(val), 420);
  });

  pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        urlInput.value = text.trim();
        updatePlatformUI(urlInput.value);
        runProbe(urlInput.value);
      }
    } catch (_) {
      urlInput.focus();
    }
  });

  clearBtn.addEventListener("click", () => {
    urlInput.value = "";
    state.videoQualities = [...DEFAULT_VIDEO_QUALITIES];
    updatePlatformUI("");
    previewCard.classList.add("hidden");
    renderQualityPills();
    urlInput.focus();
  });

  segBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      state.format = btn.dataset.format;
      segBtns.forEach((b) => {
        const active = b === btn;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
      state.quality = state.format === "mp4" ? state.videoQualities[0] : "320k";
      renderQualityPills();
    });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) {
      urlInput.focus();
      return;
    }

    if (state.activeSource) {
      state.activeSource.close();
      state.activeSource = null;
    }

    submitBtn.disabled = true;
    submitText.textContent = "RUNNING...";
    readyBox.classList.add("hidden");
    errorBox.classList.add("hidden");
    pipelineBox.classList.remove("hidden");
    progressFill.style.width = "0%";
    telemetryStatus.textContent = "STARTING";
    telemetryStats.textContent = "0.0%";

    try {
      const resp = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          format: state.format,
          quality: state.quality,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || "Invalid request.");
      }

      handleJobUpdate(data);
      if (data.stage === "ready" || data.stage === "error") return;

      const es = new EventSource(`/api/events/${data.job_id}`);
      state.activeSource = es;
      es.onmessage = (ev) => {
        const payload = JSON.parse(ev.data);
        handleJobUpdate(payload);
        if (payload.stage === "ready" || payload.stage === "error") {
          es.close();
          state.activeSource = null;
        }
      };
      es.onerror = () => {
        es.close();
        state.activeSource = null;
      };
    } catch (err) {
      handleJobUpdate({ stage: "error", percent: 0, error: err.message });
    }
  });

  clearHistoryBtn.addEventListener("click", () => {
    localStorage.removeItem("mp_history");
    renderHistory();
  });

  renderQualityPills();
  renderHistory();
})();
