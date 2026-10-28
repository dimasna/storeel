// Scene recorder: the camera in the reel's 9:16 frame, the scene's lines as a teleprompter,
// a countdown, then a review of the take before it is uploaded.

import { el, clear } from "./dom.js";

const TYPES = [
  "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
  "video/mp4",
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
];

function pickType() {
  if (!window.MediaRecorder) return null;
  return TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

export class Recorder {
  constructor({ scene, index, total, onTake, onClose }) {
    this.scene = scene;
    this.index = index;
    this.total = total;
    this.onTake = onTake;
    this.onClose = onClose;
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this.blob = null;
    this.url = null;
    this.timer = null;
    this.started = 0;
    this.state = "idle"; // idle | countdown | recording | review | uploading
  }

  async open() {
    this.root = el("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": "Record scene" });
    document.getElementById("modal-root").append(this.root);
    document.addEventListener("keydown", (this.keys = (event) => this.onKey(event)));
    this.draw();
    const type = pickType();
    if (type === null) {
      this.fail("This browser cannot record video. Try a recent Chrome, Edge, Firefox or Safari, or upload a file.");
      return;
    }
    if (!window.isSecureContext) {
      this.fail("The camera needs a secure page: open the studio at http://localhost or over https.");
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1920 } },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      if (!this.closed) this.fail(`Camera or microphone not available: ${error.message || error.name}. Allow access and try again.`);
      return;
    }
    if (this.closed) {
      // The dialog was closed while the browser was asking for the camera: release it.
      this.stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.type = type;
    this.draw();
    this.preview.srcObject = this.stream;
    this.preview.play().catch(() => {});
  }

  close() {
    if (this.state === "uploading") return;
    this.closed = true;
    clearInterval(this.timer);
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.url) URL.revokeObjectURL(this.url);
    document.removeEventListener("keydown", this.keys);
    this.root?.remove();
    this.onClose?.();
  }

  onKey(event) {
    if (event.key === "Escape") this.close();
    if (event.key === " " && event.target === document.body) {
      event.preventDefault();
      if (this.state === "idle") this.countdown();
      else if (this.state === "recording") this.stop();
    }
  }

  fail(message) {
    this.error = message;
    this.draw();
  }

  countdown() {
    if (!this.stream) return;
    this.state = "countdown";
    let left = 3;
    this.draw(left);
    this.timer = setInterval(() => {
      left -= 1;
      if (left > 0) this.draw(left);
      else {
        clearInterval(this.timer);
        this.start();
      }
    }, 800);
  }

  start() {
    this.chunks = [];
    const options = { videoBitsPerSecond: 8_000_000, audioBitsPerSecond: 128_000 };
    if (this.type) options.mimeType = this.type;
    this.recorder = new MediaRecorder(this.stream, options);
    this.recorder.ondataavailable = (event) => event.data.size && this.chunks.push(event.data);
    this.recorder.onstop = () => this.finish();
    this.recorder.start(1000);
    this.started = performance.now();
    this.state = "recording";
    this.draw();
    this.timer = setInterval(() => this.tick(), 200);
  }

  tick() {
    if (this.clock) this.clock.textContent = ((performance.now() - this.started) / 1000).toFixed(1) + "s";
  }

  stop() {
    clearInterval(this.timer);
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
  }

  finish() {
    this.blob = new Blob(this.chunks, { type: this.recorder.mimeType || this.type || "video/webm" });
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = URL.createObjectURL(this.blob);
    this.state = "review";
    this.draw();
  }

  retake() {
    this.blob = null;
    this.state = "idle";
    this.draw();
    this.preview.srcObject = this.stream;
    this.preview.play().catch(() => {});
  }

  async use() {
    if (!this.blob) return;
    const extension = (this.blob.type || "").includes("mp4") ? "mp4" : "webm";
    this.state = "uploading";
    this.draw();
    try {
      await this.onTake(this.blob, `${this.scene.id}-take.${extension}`, (fraction) => {
        if (this.bar) this.bar.style.width = `${Math.round(fraction * 100)}%`;
      });
      this.state = "done";
      this.close();
    } catch (error) {
      this.state = "review";
      this.error = error.message;
      this.draw();
    }
  }

  draw(count) {
    clear(this.root);
    const frame = el("div", { class: "recorder-frame" });
    if (this.state === "review" || this.state === "uploading") {
      frame.append(el("video", { class: "take", src: this.url, controls: true, playsinline: true, autoplay: true }));
    } else {
      this.preview = this.preview || el("video", { class: "camera", muted: true, playsinline: true, autoplay: true });
      this.preview.muted = true;
      frame.append(this.preview);
      frame.append(
        el(
          "div",
          { class: "prompter" },
          el("p", { class: "prompter-lines" }, this.scene.lines),
          this.scene.direction ? el("p", { class: "prompter-direction" }, this.scene.direction) : null,
        ),
      );
      if (this.state === "countdown") frame.append(el("div", { class: "countdown" }, String(count)));
      if (this.state === "recording") {
        this.clock = el("span", {}, "0.0s");
        frame.append(el("div", { class: "rec-badge" }, el("span", { class: "dot" }), "REC ", this.clock));
      }
    }
    const controls = el("div", { class: "recorder-controls" });
    if (this.state === "idle") {
      controls.append(
        el("button", { class: "btn primary big", onclick: () => this.countdown(), disabled: !this.stream }, "● Record"),
        el("span", { class: "hint" }, "Space to start and stop · Esc to close"),
      );
    } else if (this.state === "countdown") {
      controls.append(el("span", { class: "hint" }, "Get ready…"));
    } else if (this.state === "recording") {
      controls.append(el("button", { class: "btn danger big", onclick: () => this.stop() }, "■ Stop"));
    } else if (this.state === "review") {
      controls.append(
        el("button", { class: "btn", onclick: () => this.retake() }, "↺ Retake"),
        el("button", { class: "btn primary", onclick: () => this.use() }, "Use this take"),
      );
    } else if (this.state === "uploading") {
      this.bar = el("div", { class: "bar-fill" });
      controls.append(el("div", { class: "bar" }, this.bar), el("span", { class: "hint" }, "Uploading the take…"));
    }
    this.root.append(
      el(
        "div",
        { class: "modal-card recorder" },
        el(
          "div",
          { class: "modal-head" },
          el("h2", {}, `Scene ${this.index + 1} of ${this.total}`, this.scene.purpose ? ` · ${this.scene.purpose}` : ""),
          el("button", { class: "icon-btn", "aria-label": "Close", onclick: () => this.close() }, "✕"),
        ),
        this.error ? el("p", { class: "banner error" }, this.error) : null,
        frame,
        controls,
      ),
    );
  }
}
