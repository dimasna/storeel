// Storeel Studio: a single-page UI over the backend's actions. The backend owns the flow
// (stages, jobs, validation); this file only shows the project and calls the actions.

import { api, apiKey, upload, mediaUrl, ApiError } from "./api.js";
import { el, append, clear, toast, seconds, megabytes, ago } from "./dom.js";
import { Recorder } from "./recorder.js";

const app = document.getElementById("app");
const state = { config: null, project: null, poll: null, busy: false, uploads: [] };

const LABELS = {
  visual_style: {
    cinematic: "Cinematic photo",
    illustration: "Illustration",
    "3d": "3D animation",
    anime: "Anime",
    watercolor: "Watercolour",
    comic: "Comic",
  },
  visuals: { off: "No pictures", few: "A few", balanced: "Balanced", many: "Many" },
  captions: { pill: "Highlight pill", karaoke: "Coloured word", clean: "Plain", off: "No captions" },
  caption_position: { lower: "Lower third", middle: "Middle" },
  caption_case: { original: "As spoken", upper: "UPPERCASE" },
  watermark_position: { center: "Centre", top: "Top", bottom: "Bottom" },
  language: { auto: "Detect", id: "Indonesian (+ English)", en: "English" },
  format: { storytime: "Storytime", explainer: "Explainer", tips: "Tips", review: "Review", opinion: "Opinion" },
  tone: { casual: "Casual", energetic: "Energetic", calm: "Calm", funny: "Funny", dramatic: "Dramatic" },
  idea_language: { id: "Indonesian", en: "English" },
  picture_layout: { cards: "Cards and cut-outs over the speaker", full: "Full screen" },
  speaker_behind: { blur: "Blur the speaker", sharp: "Keep the speaker sharp", auto: "Blur only when the face is covered" },
  display: { none: "Speaker only", overlay: "Card", cutout: "Cut-out", cutaway: "Full screen" },
  novel_language: { id: "Indonesian", en: "English" },
  narration: { casual: "Casual, like telling a friend", warm: "Warm and gentle", dramatic: "Dramatic narrator", funny: "Funny gossip" },
  act: { bridge: "Bridge", setup: "Setup", rise: "Rise", turn: "Turn", cliffhanger: "Cliffhanger" },
};

const STAGES = {
  video: [
    ["upload", "Upload"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
  idea: [
    ["idea", "Idea"],
    ["record", "Script & record"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
  novel: [
    ["story", "Part script"],
    ["record", "Record"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
};

const JOB_NAMES = {
  script: "Writing the script",
  story: "Writing the part",
  process: "Processing",
  regenerate: "Regenerating a picture",
  render: "Rendering the reel",
};

// ---- small helpers ------------------------------------------------------------------------

function options(field, values, current, labels = LABELS[field]) {
  return values.map((value) =>
    el("option", { value, selected: value === current }, (labels && labels[value]) || value),
  );
}

function enumOf(schema, field) {
  // A server started before a setting existed does not offer it: the field is left out.
  return schema?.properties?.[field]?.enum ?? [];
}

function jobActive(project) {
  return Boolean(project.job && ["queued", "running"].includes(project.job.status));
}

async function act(promise, success) {
  if (state.busy) return null;
  state.busy = true;
  document.body.classList.add("busy");
  try {
    const result = await promise();
    if (result && result.id && result.stage) {
      state.project = result;
      render();
      watch();
    }
    if (success) toast(success, "ok");
    return result;
  } catch (error) {
    if (error instanceof ApiError && error.code === "api_key_required") {
      openKeyDialog(apiKey.get() ? "That key does not look right. Paste your Meta Model API key." : "Add your Meta Model API key to continue.");
      return null;
    }
    toast(error.message || String(error), "error");
    if (error instanceof ApiError && error.status === 409) refresh();
    return null;
  } finally {
    state.busy = false;
    document.body.classList.remove("busy");
  }
}

function section(title, ...children) {
  return el("section", { class: "card" }, title ? el("h2", {}, title) : null, ...children);
}

function field(label, control, hint) {
  return el("label", { class: "field" }, el("span", { class: "field-label" }, label), control, hint ? el("small", {}, hint) : null);
}

// ---- routing -------------------------------------------------------------------------------

function route() {
  const project = location.hash.match(/^#\/p\/([0-9a-f]{32})/);
  if (project) return { page: "project", id: project[1] };
  const novel = location.hash.match(/^#\/n\/([0-9a-f]{32})/);
  if (novel) return { page: "novel", id: novel[1] };
  return { page: "home" };
}

window.addEventListener("hashchange", () => start());

async function start() {
  stopWatching();
  state.project = null;
  const where = route();
  if (where.page === "home") return renderHome();
  if (where.page === "novel") return renderNovel(where.id);
  clear(app).append(el("p", { class: "muted" }, "Loading…"));
  try {
    state.project = await api.get(`/api/projects/${where.id}`);
  } catch (error) {
    clear(app).append(section("Project not found", el("p", {}, error.message), el("a", { href: "#/", class: "btn" }, "Back")));
    return;
  }
  render();
  watch();
}

// ---- polling while a job runs -------------------------------------------------------------

function stopWatching() {
  clearTimeout(state.poll);
  state.poll = null;
}

function watch() {
  stopWatching();
  if (!state.project || !jobActive(state.project)) return;
  state.poll = setTimeout(pollOnce, 1500);
}

async function pollOnce() {
  const before = state.project;
  if (!before) return;
  let after;
  try {
    after = await api.get(`/api/projects/${before.id}`);
  } catch {
    state.poll = setTimeout(pollOnce, 4000);
    return;
  }
  if (route().id !== before.id) return;
  state.project = after;
  const changed = after.job?.id !== before.job?.id || after.job?.status !== before.job?.status;
  if (changed) {
    render();
    const job = after.job;
    if (job && job.status === "done") toast(`${JOB_NAMES[job.kind] || job.kind}: done`, "ok");
    if (job && job.status === "failed") toast(`${JOB_NAMES[job.kind] || job.kind} failed`, "error");
  } else {
    updateJobPanel(after.job);
  }
  watch();
}

// ---- home ------------------------------------------------------------------------------------

async function renderHome() {
  clear(app);
  const create = (path) =>
    act(async () => {
      const project = await api.post("/api/projects", { path });
      location.hash = `#/p/${project.id}`;
      return null;
    });
  app.append(
    el(
      "section",
      { class: "hero" },
      el("h1", {}, "Create a reel"),
      el("p", { class: "muted" }, "Captions, pictures and a watermark on your talking-head video, made with Meta's Muse models."),
      el(
        "div",
        { class: "choices" },
        el(
          "button",
          { class: "choice", onclick: () => create("video") },
          el("strong", {}, "I have a video"),
          el("span", {}, "Upload one or more clips. They are transcribed, pictures are planned and drawn, and the reel is compiled."),
        ),
        el(
          "button",
          { class: "choice", onclick: () => create("idea") },
          el("strong", {}, "Not yet: start from an idea"),
          el("span", {}, `Describe the idea. ${state.config.models.script_name} writes a scene script; you record it scene by scene with a teleprompter.`),
        ),
        el(
          "button",
          { class: "choice", onclick: () => { const form = document.getElementById("new-novel"); if (form) { form.open = true; form.scrollIntoView({ behavior: "smooth" }); } } },
          el("strong", {}, "From a novel"),
          el("span", {}, "Paste a novel chapter by chapter. Each chapter becomes one part of a series: you record the part with a teleprompter, and the same characters appear in every part."),
        ),
      ),
    ),
  );
  app.append(novelsSection());
  const list = el("div", { class: "project-list" }, el("p", { class: "muted" }, "Loading projects…"));
  app.append(section("Recent reels", list));
  try {
    const projects = await api.get("/api/projects");
    clear(list);
    if (!projects.length) list.append(el("p", { class: "muted" }, "No reels yet."));
    for (const p of projects) {
      list.append(
        el(
          "a",
          { class: "project-row", href: `#/p/${p.id}` },
          p.cover ? el("img", { src: mediaUrl(p.id, p.cover), alt: "" }) : el("div", { class: "thumb-empty" }, p.path === "idea" ? "✎" : p.path === "novel" ? "❡" : "▶"),
          el("div", {}, el("strong", {}, p.title), el("small", { class: "muted" }, `${{ idea: "From an idea", novel: "Novel part", video: "From a video" }[p.path]} · ${p.stage} · ${p.input_seconds ? seconds(p.input_seconds) + " · " : ""}${ago(p.updated_at)}`)),
          p.renders ? el("span", { class: "pill ok" }, `${p.renders} render${p.renders > 1 ? "s" : ""}`) : null,
        ),
      );
    }
  } catch (error) {
    clear(list).append(el("p", { class: "banner error" }, error.message));
  }
}

// ---- project page ------------------------------------------------------------------------

function render() {
  const project = state.project;
  if (!project) return;
  clear(app);
  app.append(header(project));
  if (!apiKey.get()) {
    app.append(
      el(
        "p",
        { class: "banner warn" },
        "Add your Meta Model API key to transcribe, plan and draw pictures. Rendering works without it. ",
        el("button", { class: "btn small", onclick: () => openKeyDialog() }, "Add API key"),
      ),
    );
  }
  if (project.error && !jobActive(project)) {
    const keyProblem = /\b(401|403)\b|authentication|API key/i.test(project.error);
    app.append(
      el(
        "p",
        { class: "banner error" },
        `Last job failed: ${project.error} `,
        keyProblem ? el("button", { class: "btn small", onclick: () => openKeyDialog() }, "Update API key") : null,
      ),
    );
  }
  if (project.job && (jobActive(project) || project.job.status === "failed")) app.append(jobPanel(project));

  const locked = jobActive(project);
  const body = el("div", { class: `layout${locked ? " locked" : ""}` });
  const main = el("div", { class: "main" });
  const side = el("div", { class: "side" });
  body.append(main, side);
  app.append(body);

  const stage = project.stage;
  if (project.path === "novel") {
    main.append(partSection(project));
    if (project.story) main.append(storySection(project), takesSection(project));
  } else if (project.path === "idea") {
    main.append(ideaSection(project));
    if (project.script) main.append(scriptSection(project));
  } else {
    main.append(clipsSection(project));
  }
  if (project.path === "novel" && project.part_pictures) {
    append(main, [partPicturesSection(project), transcriptSection(project)]);
  } else if (project.analysis || project.transcript) {
    append(main, [picturesSection(project), transcriptSection(project)]);
  }
  const inputsReady = project.path === "video" ? project.clips.length > 0 : project.path === "novel" && project.clips.length ? true : project.script && project.script.scenes.every((s) => s.take);
  side.append(styleSection(project));
  if (project.path === "novel") {
    if (inputsReady || project.part_pictures) side.append(partProcessSection(project));
  } else if (inputsReady || project.analysis) side.append(processSection(project));
  if (project.analysis) side.append(renderSection(project));
  side.append(usageSection(project));
  if (stage === "processing" || stage === "rendering") body.classList.add("dim");
}

function header(project) {
  const title = el("input", {
    class: "title-input",
    value: project.title,
    maxlength: 120,
    "aria-label": "Reel title",
    onchange: (event) => {
      const value = event.target.value.trim();
      if (value && value !== project.title) act(() => api.patch(`/api/projects/${project.id}`, { title: value }));
    },
  });
  const steps = STAGES[project.path];
  const order = steps.map(([key]) => key);
  const aliases = { scripting: project.path === "novel" ? "story" : "idea", regenerating: "review", rendering: "done" };
  const current = aliases[project.stage] || project.stage;
  const position = Math.max(0, order.indexOf(current));
  return el(
    "div",
    { class: "project-head" },
    el("a", { href: project.novel ? `#/n/${project.novel.id}` : "#/", class: "back" }, project.novel ? `← ${project.novel.title}` : "← All reels"),
    title,
    el(
      "ol",
      { class: "stepper" },
      steps.map(([key, label], i) => el("li", { class: i < position ? "done" : i === position ? "now" : "" }, label)),
    ),
  );
}

function jobPanel(project) {
  const job = project.job;
  const panel = el("section", { class: `card job ${job.status}`, id: "job-panel" });
  const bar = el("div", { class: "bar-fill", style: `width:${Math.round((job.progress || 0) * 100)}%` });
  const log = el("pre", { class: "log" }, job.log || "");
  append(panel, [
    el(
      "div",
      { class: "job-head" },
      el("strong", { class: "job-title" }, JOB_NAMES[job.kind] || job.kind),
      el("span", { class: "job-step muted" }, job.status === "queued" ? "waiting for a worker…" : job.step || ""),
      jobActive(project)
        ? el("button", { class: "btn small", disabled: job.cancel_requested, onclick: () => act(() => api.post(`/api/jobs/${job.id}/cancel`), "Cancelling…") }, job.cancel_requested ? "Cancelling…" : "Cancel")
        : null,
    ),
    el("div", { class: "bar" }, bar),
    job.status === "failed" ? el("p", { class: "banner error" }, job.error || "failed") : null,
    el("details", { open: job.status === "failed" }, el("summary", {}, "Log"), log),
  ]);
  return panel;
}

function updateJobPanel(job) {
  const panel = document.getElementById("job-panel");
  if (!panel || !job) return;
  panel.querySelector(".bar-fill").style.width = `${Math.round((job.progress || 0) * 100)}%`;
  panel.querySelector(".job-step").textContent = job.status === "queued" ? "waiting for a worker…" : job.step || "";
  const log = panel.querySelector(".log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  log.textContent = job.log || "";
  if (atBottom) log.scrollTop = log.scrollHeight;
}

// ---- path A: clips --------------------------------------------------------------------------

function clipsSection(project) {
  const list = el("ol", { class: "clip-list" });
  project.clips.forEach((clip, index) => {
    const move = (delta) => {
      const ids = project.clips.map((c) => c.id);
      const [moved] = ids.splice(index, 1);
      ids.splice(index + delta, 0, moved);
      act(() => api.put(`/api/projects/${project.id}/clips/order`, { ids }));
    };
    list.append(
      el(
        "li",
        { class: "clip" },
        el("video", { src: mediaUrl(project.id, clip.key), preload: "metadata", muted: true, playsinline: true, controls: true }),
        el(
          "div",
          { class: "clip-info" },
          el("strong", {}, clip.name),
          el("small", { class: "muted" }, `${seconds(clip.duration)} · ${clip.width}×${clip.height} · ${Math.round(clip.fps)} fps${clip.has_audio ? "" : " · no sound"}${clip.hdr ? " · HDR" : ""} · ${megabytes(clip.size)}`),
        ),
        el(
          "div",
          { class: "row-actions" },
          el("button", { class: "icon-btn", title: "Move up", disabled: index === 0, onclick: () => move(-1) }, "↑"),
          el("button", { class: "icon-btn", title: "Move down", disabled: index === project.clips.length - 1, onclick: () => move(1) }, "↓"),
          el("button", { class: "icon-btn", title: "Remove", onclick: () => confirm(`Remove ${clip.name}?`) && act(() => api.del(`/api/projects/${project.id}/clips/${clip.id}`)) }, "✕"),
        ),
      ),
    );
  });
  const picker = el("input", { type: "file", accept: "video/*", multiple: true, hidden: true, onchange: (event) => uploadClips(project, [...event.target.files]) });
  const drop = el(
    "div",
    {
      class: "dropzone",
      tabindex: 0,
      role: "button",
      onclick: () => picker.click(),
      onkeydown: (event) => (event.key === "Enter" || event.key === " ") && picker.click(),
      ondragover: (event) => {
        event.preventDefault();
        drop.classList.add("over");
      },
      ondragleave: () => drop.classList.remove("over"),
      ondrop: (event) => {
        event.preventDefault();
        drop.classList.remove("over");
        uploadClips(project, [...event.dataTransfer.files].filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm|mkv)$/i.test(f.name)));
      },
    },
    el("strong", {}, "Drop video clips here, or click to choose"),
    el("small", { class: "muted" }, `MP4, MOV or WebM · up to ${state.config.max_input_seconds}s in total · clips play in this order`),
    picker,
  );
  const progress = el("div", { id: "upload-progress" });
  const body = [
    project.clips.length ? list : null,
    el("p", { class: "muted small" }, project.clips.length ? `Total ${seconds(project.input_seconds)} of ${state.config.max_input_seconds}s.` : "Portrait (9:16) works best; other shapes are centre-cropped."),
    drop,
    progress,
  ];
  if (project.analysis) {
    const count = `${project.clips.length} clip${project.clips.length === 1 ? "" : "s"} · ${seconds(project.input_seconds)}`;
    return section(null, el("details", {}, el("summary", {}, el("strong", {}, "Your video: "), count, " (changing clips means processing again)"), ...body));
  }
  return section("Your video", ...body);
}

async function uploadClips(project, files) {
  if (!files.length) return;
  const box = document.getElementById("upload-progress");
  for (const file of files) {
    const bar = el("div", { class: "bar-fill" });
    const row = el("div", { class: "upload-row" }, el("span", {}, file.name), el("div", { class: "bar" }, bar));
    box?.append(row);
    try {
      state.project = await upload(`/api/projects/${project.id}/clips`, file, file.name, (f) => (bar.style.width = `${Math.round(f * 100)}%`));
      toast(`Added ${file.name}`, "ok");
    } catch (error) {
      toast(`${file.name}: ${error.message}`, "error");
    } finally {
      row.remove();
    }
  }
  render();
}

// ---- path B: idea, script, recording ------------------------------------------------------

function ideaSection(project) {
  const schema = state.config.idea;
  const idea = project.idea || { text: "", format: "storytime", tone: "casual", length: 30, language: "id" };
  const text = el("textarea", { rows: 4, maxlength: 2000, placeholder: "What is the reel about? A story, a tip, an opinion…" }, idea.text);
  const format = el("select", {}, options("format", enumOf(schema, "format"), idea.format));
  const tone = el("select", {}, options("tone", enumOf(schema, "tone"), idea.tone));
  const language = el("select", {}, options("idea_language", ["id", "en"], idea.language));
  const length = el("input", { type: "range", min: 15, max: 90, step: 5, value: idea.length });
  const lengthLabel = el("output", {}, `${idea.length}s`);
  length.addEventListener("input", () => (lengthLabel.textContent = `${length.value}s`));
  const write = () => {
    if (text.value.trim().length < 3) return toast("Describe the idea first", "error");
    const takes = project.script ? project.script.scenes.filter((s) => s.take).length : 0;
    if (takes && !confirm(`A new script replaces the current one and deletes ${takes} recorded take(s). Continue?`)) return;
    act(
      () => api.put(`/api/projects/${project.id}/idea`, { text: text.value.trim(), format: format.value, tone: tone.value, length: Number(length.value), language: language.value }),
      `${state.config.models.script_name} is writing the script…`,
    );
  };
  const open = !project.script;
  const body = el(
    "div",
    { class: "form" },
    field("Idea or topic", text),
    el("div", { class: "grid3" }, field("Format", format), field("Tone", tone), field("Language", language)),
    field("Length", el("div", { class: "range" }, length, lengthLabel)),
    el("button", { class: "btn primary", onclick: write }, project.script ? "Write a new script" : "Write the script"),
  );
  if (open) return section("Your idea", body);
  return section(null, el("details", {}, el("summary", {}, el("strong", {}, "Your idea: "), idea.text.slice(0, 90), idea.text.length > 90 ? "…" : ""), body));
}

function scriptSection(project) {
  const script = structuredClone(project.script);
  let dirty = false;
  const save = el("button", { class: "btn", disabled: true }, "Save script");
  const markDirty = () => {
    dirty = true;
    save.disabled = false;
  };
  const payload = () => ({
    title: titleInput.value.trim() || "Untitled",
    language: script.language,
    entities: script.entities,
    scenes: script.scenes.map(({ take, ...scene }) => scene),
  });
  save.addEventListener("click", () => act(() => api.put(`/api/projects/${project.id}/script`, payload()), "Script saved"));
  const titleInput = el("input", { value: script.title, maxlength: 120, oninput: markDirty });
  const list = el("ol", { class: "scenes" });
  const redraw = () => {
    clear(list);
    script.scenes.forEach((scene, index) => list.append(sceneCard(project, script, scene, index, markDirty, redraw, () => dirty)));
  };
  redraw();
  const add = el(
    "button",
    {
      class: "btn small",
      onclick: () => {
        const used = new Set(script.scenes.map((s) => s.id));
        let n = script.scenes.length + 1;
        while (used.has(`s${n}`)) n += 1;
        script.scenes.push({ id: `s${n}`, purpose: "story", lines: "…", direction: "", display: "none", visual: "", entities: [], take: null });
        markDirty();
        redraw();
      },
    },
    "+ Add scene",
  );
  const recorded = script.scenes.filter((s) => s.take).length;
  const content = [
    el("p", { class: "muted small" }, `${script.scenes.length} scenes · ${recorded} recorded · about ${script.scenes.reduce((n, s) => n + s.lines.split(/\s+/).length, 0)} words. Record each scene in one take; edit the lines first if they don't sound like you.`),
    field("Title", titleInput),
    list,
    el("div", { class: "row" }, add, save),
  ];
  if (project.analysis) {
    return section(null, el("details", {}, el("summary", {}, el("strong", {}, "Script and takes: "), `${script.scenes.length} scenes recorded (a new take means processing again)`), ...content));
  }
  return section("Script", ...content);
}

function sceneCard(project, script, scene, index, markDirty, redraw, isDirty) {
  const lines = el("textarea", { rows: 2, maxlength: 600, oninput: (e) => ((scene.lines = e.target.value), markDirty()) }, scene.lines);
  const direction = el("input", { value: scene.direction, maxlength: 300, placeholder: "delivery note", oninput: (e) => ((scene.direction = e.target.value), markDirty()) });
  const visual = el("textarea", { rows: 2, maxlength: 800, placeholder: "English: the picture shown while this scene is spoken", oninput: (e) => ((scene.visual = e.target.value), markDirty()) }, scene.visual);
  const display = el(
    "select",
    {
      onchange: (e) => {
        scene.display = e.target.value;
        visualField.hidden = scene.display === "none";
        markDirty();
      },
    },
    options("display", ["none", "overlay", "cutout", "cutaway"], scene.display),
  );
  const visualField = field("Picture", visual);
  visualField.hidden = scene.display === "none";
  const move = (delta) => {
    const [item] = script.scenes.splice(index, 1);
    script.scenes.splice(index + delta, 0, item);
    markDirty();
    redraw();
  };
  const remove = () => {
    if (scene.take && !confirm("This scene has a recorded take. Delete the scene and its take when you save?")) return;
    script.scenes.splice(index, 1);
    markDirty();
    redraw();
  };
  const record = () => {
    if (isDirty()) return toast("Save the script before recording", "error");
    const recorder = new Recorder({
      scene,
      index,
      total: script.scenes.length,
      onTake: async (blob, name, progress) => {
        state.project = await upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, blob, name, progress);
        toast(`Scene ${index + 1} recorded`, "ok");
      },
      onClose: () => render(),
    });
    recorder.open();
  };
  const filePicker = el("input", {
    type: "file",
    accept: "video/*",
    hidden: true,
    onchange: async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      if (isDirty()) return toast("Save the script before adding takes", "error");
      await act(() => upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, file, file.name), `Scene ${index + 1}: take added`);
    },
  });
  const take = scene.take
    ? el(
        "div",
        { class: "take-row" },
        el("video", { src: mediaUrl(project.id, scene.take.key), controls: true, playsinline: true, preload: "metadata" }),
        el("span", { class: "pill ok" }, `recorded · ${seconds(scene.take.duration)}`),
        el("button", { class: "btn small", onclick: record }, "Retake"),
        el("button", { class: "icon-btn", title: "Delete take", onclick: () => confirm("Delete this take?") && act(() => api.del(`/api/projects/${project.id}/scenes/${scene.id}/take`)) }, "✕"),
      )
    : el(
        "div",
        { class: "take-row" },
        el("button", { class: "btn primary small", onclick: record }, "● Record"),
        el("button", { class: "btn small", onclick: () => filePicker.click() }, "Upload a take"),
        filePicker,
      );
  return el(
    "li",
    { class: `scene${scene.take ? " recorded" : ""}` },
    el(
      "div",
      { class: "scene-head" },
      el("span", { class: "scene-n" }, String(index + 1)),
      el("span", { class: "muted small" }, scene.purpose || ""),
      el(
        "div",
        { class: "row-actions" },
        el("button", { class: "icon-btn", title: "Move up", disabled: index === 0, onclick: () => move(-1) }, "↑"),
        el("button", { class: "icon-btn", title: "Move down", disabled: index === script.scenes.length - 1, onclick: () => move(1) }, "↓"),
        el("button", { class: "icon-btn", title: "Delete scene", disabled: script.scenes.length === 1, onclick: remove }, "✕"),
      ),
    ),
    field("Lines", lines),
    el("div", { class: "grid2" }, field("Delivery", direction), field("While spoken", display)),
    visualField,
    take,
  );
}

// ---- novels -----------------------------------------------------------------------------------

function novelMediaUrl(novelId, key) {
  return `/api/novels/${novelId}/media/${key.split("/").map(encodeURIComponent).join("/")}`;
}

// The novel's fields, for a new novel or an existing one. `onSave(fields)` stores them.
function novelForm(novel, onSave, saveLabel) {
  const schema = state.config.novel;
  const values = { title: "", synopsis: "", language: "id", narration: "casual", visual_style: "cinematic", watermark: "", ...(novel || {}) };
  const title = el("input", { value: values.title, maxlength: 120, placeholder: "The novel's title" });
  const synopsis = el("textarea", { rows: 3, maxlength: 4000, placeholder: "A few sentences about the story (optional, helps the script)" }, values.synopsis);
  const language = el("select", {}, options("novel_language", enumOf(schema, "language"), values.language));
  const narration = el("select", {}, options("narration", enumOf(schema, "narration"), values.narration));
  const look = el("select", {}, options("visual_style", enumOf(schema, "visual_style"), values.visual_style));
  const watermark = el("input", { value: values.watermark, maxlength: 60, placeholder: "@yourname" });
  const sample = el("small", { class: "muted" });
  const describe = () => {
    const option = state.config.narration?.[language.value]?.[narration.value];
    clear(sample).append(option ? `Part one opens: “${option.opening}...” · ${option.voice}` : "");
  };
  language.addEventListener("change", describe);
  narration.addEventListener("change", describe);
  describe();
  const save = () => {
    if (!title.value.trim()) return toast("Give the novel a title", "error");
    onSave({
      title: title.value.trim(),
      synopsis: synopsis.value.trim(),
      language: language.value,
      narration: narration.value,
      visual_style: look.value,
      watermark: watermark.value.trim(),
    });
  };
  return el(
    "div",
    { class: "form" },
    field("Title", title),
    field("Synopsis", synopsis),
    el("div", { class: "grid3" }, field("Language", language), field("Narration style", narration), field("Picture look", look)),
    sample,
    field("Watermark", watermark, "Shown on every part, e.g. where to read the novel."),
    el("button", { class: "btn primary", onclick: save }, saveLabel),
  );
}

function novelsSection() {
  const list = el("div", { class: "project-list" }, el("p", { class: "muted" }, "Loading novels…"));
  const form = novelForm(null, (fields) =>
    act(async () => {
      const novel = await api.post("/api/novels", fields);
      location.hash = `#/n/${novel.id}`;
      return null;
    }), "Create the novel");
  (async () => {
    try {
      const novels = await api.get("/api/novels");
      clear(list);
      if (!novels.length) list.append(el("p", { class: "muted" }, "No novels yet."));
      for (const n of novels) {
        list.append(
          el(
            "a",
            { class: "project-row", href: `#/n/${n.id}` },
            el("div", { class: "thumb-empty" }, "❡"),
            el("div", {}, el("strong", {}, n.title), el("small", { class: "muted" }, `${n.chapters} chapter${n.chapters === 1 ? "" : "s"} · ${n.characters} character${n.characters === 1 ? "" : "s"} in the bible · ${ago(n.updated_at)}`)),
          ),
        );
      }
    } catch (error) {
      clear(list).append(el("p", { class: "banner error" }, error.message));
    }
  })();
  return section("Novels", list, el("details", { id: "new-novel" }, el("summary", {}, el("strong", {}, "New novel")), form));
}

async function renderNovel(id) {
  clear(app).append(el("p", { class: "muted" }, "Loading…"));
  let novel;
  try {
    novel = await api.get(`/api/novels/${id}`);
  } catch (error) {
    clear(app).append(section("Novel not found", el("p", {}, error.message), el("a", { href: "#/", class: "btn" }, "Back")));
    return;
  }
  const reload = () => renderNovel(id);
  const saveFields = (fields) => act(async () => { await api.put(`/api/novels/${id}`, fields); reload(); return null; }, "Saved");
  const openPart = (number) =>
    act(async () => {
      const project = await api.post(`/api/novels/${id}/chapters/${number}/reel`);
      location.hash = `#/p/${project.id}`;
      return null;
    });
  const removeChapter = (c) =>
    confirm(`Delete chapter ${c.number}${c.project_id ? " and its reel (takes and renders)" : ""}? What it added to the character bible goes too.`) &&
    act(async () => { await api.del(`/api/novels/${id}/chapters/${c.number}`); reload(); return null; }, "Chapter deleted");
  const chapters = novel.chapters.length
    ? el(
        "table",
        { class: "chapters" },
        el("tr", {}, el("th", {}, "Part"), el("th", {}, "Title"), el("th", {}, "Text"), el("th", {}, "Reel"), el("th", {}, "")),
        novel.chapters.map((c) =>
          el(
            "tr",
            {},
            el("td", {}, String(c.number)),
            el("td", {}, c.title || el("span", { class: "muted" }, "untitled")),
            el("td", { class: "muted small" }, `${c.chars.toLocaleString()} chars`),
            el("td", {}, c.stage ? el("span", { class: `pill${c.renders ? " ok" : ""}` }, c.renders ? `${c.renders} render${c.renders > 1 ? "s" : ""}` : c.stage) : el("span", { class: "muted small" }, "not started")),
            el(
              "td",
              { class: "row-actions" },
              el("button", { class: "btn small primary", onclick: () => openPart(c.number) }, c.project_id ? "Open" : "Make the part"),
              el("button", { class: "icon-btn", title: "Delete chapter", onclick: () => removeChapter(c) }, "✕"),
            ),
          ),
        ),
      )
    : el("p", { class: "muted" }, "No chapters yet. Add the first one below.");
  const number = el("input", { type: "number", min: 1, max: 999, value: novel.next_chapter });
  const ctitle = el("input", { maxlength: 160, placeholder: "optional" });
  const ctext = el("textarea", { rows: 10, maxlength: 200000, placeholder: "Paste the whole chapter text here" });
  const addChapter = () => {
    if (ctext.value.trim().length < 200) return toast("Paste the whole chapter text (at least a few paragraphs)", "error");
    act(async () => {
      await api.post(`/api/novels/${id}/chapters`, { number: Number(number.value) || null, title: ctitle.value.trim(), text: ctext.value });
      reload();
      return null;
    }, "Chapter added");
  };
  const removeNovel = () =>
    confirm(`Delete “${novel.title}”, its character bible and every part's reel?`) &&
    act(async () => { await api.del(`/api/novels/${id}`); location.hash = "#/"; return null; }, "Novel deleted");
  clear(app).append(
    el("div", { class: "project-head" }, el("a", { href: "#/", class: "back" }, "← All reels"), el("h1", {}, novel.title)),
    el(
      "div",
      { class: "layout" },
      el(
        "div",
        { class: "main" },
        section("Chapters", el("p", { class: "muted small" }, "Each chapter is one part of the series: one reel with a hook, the story, a poll and a call to action."), chapters),
        section(
          "Add a chapter",
          el("div", { class: "form" }, el("div", { class: "grid2" }, field("Part number", number), field("Chapter title", ctitle)), field("Chapter text", ctext), el("button", { class: "btn primary", onclick: addChapter }, "Add chapter")),
        ),
        bibleSection(novel),
      ),
      el(
        "div",
        { class: "side" },
        section("The novel", novelForm(novel, saveFields, "Save")),
        section(null, el("button", { class: "btn danger small", onclick: removeNovel }, "Delete novel")),
      ),
    ),
  );
}

function bibleSection(novel) {
  const characters = Object.values(novel.bible.characters || {});
  const props = Object.values(novel.bible.props || {});
  if (!characters.length && !props.length) {
    return section("Character bible", el("p", { class: "muted" }, "Empty. The first part you process designs its characters here; later parts reuse them, so every part shows the same people."));
  }
  const picture = (key, alt) => (key ? el("img", { src: novelMediaUrl(novel.id, key), alt, loading: "lazy" }) : el("div", { class: "thumb-empty" }, alt.slice(0, 1).toUpperCase()));
  return section(
    "Character bible",
    el(
      "div",
      { class: "bible" },
      characters.map((c) => {
        const latest = [...c.looks].sort((a, b) => b.chapter - a.chapter)[0];
        return el(
          "div",
          { class: "bible-card" },
          picture(latest?.image, c.name),
          el(
            "div",
            {},
            el("strong", {}, c.name),
            el("small", { class: "muted" }, ` “${c.label}” · ${c.role} · since part ${c.created_in}`),
            el("p", { class: "small" }, c.description),
            c.looks.length ? el("div", { class: "looks" }, c.looks.map((x) => el("span", { class: "look", title: x.outfit }, x.image ? el("img", { src: novelMediaUrl(novel.id, x.image), alt: "" }) : null, `part ${x.chapter}`))) : null,
            c.notes.map((n) => el("p", { class: "note" }, `Part ${n.chapter}: ${n.note}`)),
          ),
        );
      }),
      props.map((p) => el("div", { class: "bible-card" }, picture(p.image, p.id), el("div", {}, el("strong", {}, p.id), el("small", { class: "muted" }, ` object · since part ${p.created_in}`), el("p", { class: "small" }, p.description)))),
    ),
  );
}

// ---- a novel part: its script and takes -------------------------------------------------------

function partSection(project) {
  const part = project.novel;
  const write = () => {
    const takes = project.script ? project.script.scenes.filter((s) => s.take).length : 0;
    if (takes && !confirm(`A new script replaces this one and deletes ${takes} recorded take(s). Continue?`)) return;
    act(() => api.post(`/api/projects/${project.id}/story`), `${state.config.models.script_name} is writing the part…`);
  };
  return section(
    project.story ? null : `Part ${project.chapter}`,
    part
      ? el("details", {}, el("summary", {}, el("strong", {}, `Chapter ${project.chapter}${part.chapter_title ? `: ${part.chapter_title}` : ""}`), el("span", { class: "muted small" }, ` · ${part.chapter_text.length.toLocaleString()} chars`)), el("div", { class: "chapter-text" }, part.chapter_text))
      : el("p", { class: "banner warn" }, "This reel's novel was deleted."),
    el(
      "p",
      { class: "muted small" },
      project.story
        ? "Rewrite the part if it misses the chapter's best moments. Edit single words below instead: that keeps your takes."
        : `${state.config.models.script_name} writes the part from the chapter and the character bible: the hook, the story beats, a poll and the call to action. You then record it in a few takes.`,
    ),
    part ? el("button", { class: "btn primary", onclick: write }, project.story ? "Rewrite the part" : "Write the part") : null,
  );
}

function showTags(show, prefix = "") {
  const tags = [];
  (show.characters || []).forEach((c) => tags.push(["c", c]));
  if (show.prop) tags.push(["p", `object: ${show.prop}`]);
  if (show.photo) tags.push(["ph", `photo: ${show.photo}`]);
  (show.chat || []).forEach((m) => tags.push(["ch", `chat ${m.sender}: ${m.text}`]));
  if (show.note && show.note.text) tags.push(["ch", `note: ${show.note.text}`]);
  if (show.tag) tags.push(["t", show.tag]);
  if (!tags.length) return null;
  return el("div", { class: "tags" }, prefix ? el("span", { class: "muted small" }, prefix) : null, tags.map(([kind, text]) => el("span", { class: `tag ${kind}` }, text)));
}

function storySection(project) {
  const story = structuredClone(project.story);
  const save = el("button", { class: "btn primary", disabled: true }, "Save the words");
  const dirty = () => (save.disabled = false);
  const input = (value, attrs, onInput) => el("input", { value, oninput: (e) => (onInput(e.target.value), dirty()), ...attrs });
  const area = (value, attrs, onInput) => el("textarea", { rows: Math.max(2, Math.ceil(value.length / 70)), oninput: (e) => (onInput(e.target.value), dirty()), ...attrs }, value);
  const opening = project.novel?.opening;
  save.addEventListener("click", () =>
    act(
      () =>
        api.put(`/api/projects/${project.id}/story`, {
          chapter_title: story.chapter_title,
          hook: story.hook,
          hook_direction: story.hook_direction,
          beats: story.beats.map((b) => ({ text: b.text, direction: b.direction })),
          poll: story.poll,
          cta: story.cta,
        }),
      "Saved. Re-record any take whose words you changed.",
    ),
  );
  const chars = [story.hook, ...story.beats.map((b) => b.text), story.poll.text, story.cta].join(" ").length;
  const beats = story.beats.map((b, i) =>
    el(
      "li",
      { class: "beat" },
      el("div", { class: "beat-head small muted" }, `Beat ${i + 1} · ${LABELS.act[b.act] || b.act} · take ${b.take.slice(1)}${b.speaker !== "narrator" ? ` · quoting ${b.speaker}` : ""}`),
      area(b.text, { maxlength: 400 }, (v) => (b.text = v)),
      input(b.direction, { maxlength: 200, placeholder: "delivery note", class: "direction" }, (v) => (b.direction = v)),
      showTags(b.show),
      b.switch ? showTags(b.switch.show, `at “${b.switch.at}” →`) : null,
    ),
  );
  const list = (title, items, fmt) => (items && items.length ? [el("h3", {}, title), el("ul", { class: "small plain" }, items.map((x) => el("li", {}, fmt(x))))] : []);
  return section(
    "Part script",
    el("p", { class: "muted small" }, `Part ${story.part} · ${story.beats.length} beats · ${chars.toLocaleString()} characters, about ${Math.round(chars / 13.5)} seconds read aloud.`),
    story.problems.length ? el("div", { class: "banner warn small" }, el("strong", {}, "Still to fix: "), story.problems.join("; ")) : null,
    field("Part title", input(story.chapter_title, { maxlength: 120 }, (v) => (story.chapter_title = v))),
    el(
      "ol",
      { class: "beats" },
      el(
        "li",
        { class: "beat hook" },
        el("div", { class: "beat-head small muted" }, `Hook · on camera · take 1${opening ? ` · starts with “${opening}...”` : ""}`),
        area(story.hook, { maxlength: 400 }, (v) => (story.hook = v)),
        input(story.hook_direction, { maxlength: 200, placeholder: "delivery note", class: "direction" }, (v) => (story.hook_direction = v)),
      ),
      beats,
      el(
        "li",
        { class: "beat" },
        el("div", { class: "beat-head small muted" }, "Poll · two options on screen · ends with the invitation to comment"),
        area(story.poll.text, { maxlength: 400 }, (v) => (story.poll.text = v)),
        el("div", { class: "grid2" }, field("Option A", input(story.poll.a, { maxlength: 40 }, (v) => (story.poll.a = v))), field("Option B", input(story.poll.b, { maxlength: 40 }, (v) => (story.poll.b = v)))),
      ),
      el(
        "li",
        { class: "beat" },
        el("div", { class: "beat-head small muted" }, "Call to action · over the end card"),
        area(story.cta, { maxlength: 400 }, (v) => (story.cta = v)),
      ),
    ),
    el("div", { class: "row" }, save),
    el(
      "details",
      {},
      el("summary", {}, "Characters, outfits and pictures in this part"),
      ...list("New characters (they join the bible)", story.characters, (c) => `${c.name} (${c.id}, “${c.label}”, ${c.role}): ${c.description}. Wears: ${c.outfit}`),
      ...list("Returning characters' outfits", story.looks, (x) => `${x.id}: ${x.outfit}`),
      ...list("Variants", story.variants, (v) => `${v.id} (${v.base}): ${v.change}${v.persistent ? " (lasting)" : ""}`),
      ...list("Objects and scenes", story.props, (p) => `${p.id}${p.recurring ? " (recurring)" : ""}: ${p.description}`),
      ...list("Photos", story.photos, (p) => `${p.id} “${p.title}”: ${p.description}`),
      ...list("Notes for the bible", story.bible_notes, (x) => `${x.id}: ${x.note}`),
    ),
  );
}

// ---- a novel part: processing and its pictures ------------------------------------------------

function partProcessSection(project) {
  const processed = Boolean(project.part_pictures);
  return section(
    processed ? "Pictures" : "Process",
    el(
      "p",
      { class: "muted small" },
      processed
        ? "Update after a retake or a script change: only what changed is made again."
        : "Transcribes your takes, then draws the part's pictures with Muse Image: characters from the bible (cut out by SAM, the same faces as in earlier parts), objects, places and photos.",
    ),
    el("button", { class: "btn primary", onclick: () => act(() => api.post(`/api/projects/${project.id}/process`, { fresh: false }), processed ? "Updating…" : "Processing started") }, processed ? "Update" : "Process the part"),
  );
}

function partPicturesSection(project) {
  const pictures = Object.values(project.part_pictures || {});
  const url = (p) => (p.scope === "novel" && project.novel ? novelMediaUrl(project.novel.id, p.key) : mediaUrl(project.id, p.key));
  const how = { standing: "stands at the bottom", object: "cut-out object", card: "card" };
  return section(
    "The part's pictures",
    el("p", { class: "muted small" }, "Characters come from the novel's bible; a returning character is redrawn in this part's outfit from their earlier portrait."),
    el(
      "div",
      { class: "bible" },
      pictures.map((p) =>
        el(
          "div",
          { class: "bible-card" },
          p.key ? el("a", { href: url(p), target: "_blank", rel: "noopener" }, el("img", { src: url(p), alt: p.id, loading: "lazy" })) : el("div", { class: "thumb-empty" }, "!"),
          el(
            "div",
            {},
            el("strong", {}, p.id),
            el("small", { class: "muted" }, ` ${p.kind} · ${how[p.display] || p.display}${p.display !== "card" && !p.cutout && p.key ? " (not cut out: shown framed)" : ""}`),
            p.error ? el("p", { class: "banner error small" }, p.error) : null,
          ),
        ),
      ),
    ),
  );
}

function takesSection(project) {
  const scenes = project.script ? project.script.scenes : [];
  const recorded = scenes.filter((s) => s.take).length;
  const whole = project.clips[0];
  const picker = el("input", {
    type: "file",
    accept: "video/*",
    hidden: true,
    onchange: async (event) => {
      const file = event.target.files[0];
      if (file) await act(() => upload(`/api/projects/${project.id}/clips`, file, file.name), "Video added");
    },
  });
  const wholeVideo = whole
    ? el(
        "div",
        { class: "take-row" },
        el("video", { src: mediaUrl(project.id, whole.key), controls: true, playsinline: true, preload: "metadata" }),
        el("span", { class: "pill ok" }, `one video · ${seconds(whole.duration)}`),
        el("button", { class: "icon-btn", title: "Remove the video", onclick: () => confirm("Remove this video? The takes (if any) are used again.") && act(() => api.del(`/api/projects/${project.id}/clips/${whole.id}`)) }, "✕"),
      )
    : el("div", { class: "take-row" }, el("button", { class: "btn small", onclick: () => picker.click() }, "Upload one video of the whole part"), picker);
  return section(
    "Record the part",
    el("p", { class: "muted small" }, whole
      ? "This video is used instead of the takes. Its words are matched to the script to time the pictures."
      : `${scenes.length} takes · ${recorded} recorded. Read each take from the teleprompter in one go; the delivery notes show under the lines. Or record the whole part elsewhere and upload it as one video.`),
    wholeVideo,
    whole ? null : el("ol", { class: "scenes" }, scenes.map((scene, index) => takeCard(project, scenes, scene, index))),
  );
}

function takeCard(project, scenes, scene, index) {
  const record = () => {
    const recorder = new Recorder({
      scene,
      index,
      total: scenes.length,
      onTake: async (blob, name, progress) => {
        state.project = await upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, blob, name, progress);
        toast(`Take ${index + 1} recorded`, "ok");
      },
      onClose: () => render(),
    });
    recorder.open();
  };
  const picker = el("input", {
    type: "file",
    accept: "video/*",
    hidden: true,
    onchange: async (event) => {
      const file = event.target.files[0];
      if (file) await act(() => upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, file, file.name), `Take ${index + 1} added`);
    },
  });
  const controls = scene.take
    ? el(
        "div",
        { class: "take-row" },
        el("video", { src: mediaUrl(project.id, scene.take.key), controls: true, playsinline: true, preload: "metadata" }),
        el("span", { class: "pill ok" }, `recorded · ${seconds(scene.take.duration)}`),
        el("button", { class: "btn small", onclick: record }, "Retake"),
        el("button", { class: "icon-btn", title: "Delete take", onclick: () => confirm("Delete this take?") && act(() => api.del(`/api/projects/${project.id}/scenes/${scene.id}/take`)) }, "✕"),
      )
    : el("div", { class: "take-row" }, el("button", { class: "btn primary small", onclick: record }, "● Record"), el("button", { class: "btn small", onclick: () => picker.click() }, "Upload a take"), picker);
  return el(
    "li",
    { class: `scene${scene.take ? " recorded" : ""}` },
    el("div", { class: "scene-head" }, el("span", { class: "scene-n" }, String(index + 1)), el("span", { class: "muted small" }, scene.purpose)),
    el("p", { class: "take-lines" }, scene.lines),
    scene.direction ? el("p", { class: "muted small" }, scene.direction) : null,
    controls,
  );
}

// ---- style --------------------------------------------------------------------------------

function styleSection(project) {
  const schema = state.config.style;
  const style = { ...project.style };
  let timer = null;
  // Saved quietly: re-rendering the page here would take the cursor out of the field.
  const save = async () => {
    try {
      state.project = await api.put(`/api/projects/${project.id}/style`, style);
    } catch (error) {
      toast(error.message, "error");
    }
  };
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(save, 600);
  };
  const select = (name, label, hint) => {
    const values = enumOf(schema, name);
    if (!values.length) return null;
    return field(label, el("select", { onchange: (e) => ((style[name] = e.target.value), save()) }, options(name, values, style[name])), hint);
  };
  const color = el("input", { type: "color", value: style.caption_color, onchange: (e) => ((style.caption_color = e.target.value.toUpperCase()), save()) });
  const watermark = el("input", { value: style.watermark, maxlength: 60, placeholder: "@yourname", oninput: (e) => ((style.watermark = e.target.value), later()) });
  const pictures = project.analysis ? "Picture changes apply when you update the pictures." : null;
  return section(
    "Style",
    el(
      "div",
      { class: "form" },
      el("h3", {}, "Pictures"),
      select("visual_style", "Look", pictures),
      select("visuals", "How many"),
      select("picture_layout", "Layout", "Each picture can also be changed in Review."),
      select("speaker_behind", "Speaker behind a card or cut-out", "Applies when you render. “Blur only when the face is covered” checks the face, so update the pictures after choosing it."),
      project.path === "video" ? select("language", "Spoken language") : null,
      el("h3", {}, "Captions"),
      select("captions", "Style"),
      el("div", { class: "grid2" }, field("Highlight", color), select("caption_case", "Case")),
      select("caption_position", "Position"),
      el("h3", {}, "Watermark"),
      field("Text", watermark),
      select("watermark_position", "Position"),
    ),
  );
}

// ---- processing ----------------------------------------------------------------------------

function processSection(project) {
  const processed = Boolean(project.analysis);
  const run = (fresh) =>
    act(() => api.post(`/api/projects/${project.id}/process`, { fresh }), processed ? "Updating the pictures…" : "Processing started");
  return section(
    processed ? "Pictures" : "Process",
    el(
      "p",
      { class: "muted small" },
      processed
        ? "Update applies style changes and redoes only what changed. Redo makes a new picture for every moment."
        : `Transcribes the speech (Muse Voice Transcribe), plans the pictures (${state.config.models.plan_name}), finds faces and references (SAM 3.1) and draws the pictures (Muse Image).`,
    ),
    el(
      "div",
      { class: "row" },
      el("button", { class: "btn primary", onclick: () => run(false) }, processed ? "Update pictures" : "Process the video"),
      processed
        ? el("button", { class: "btn", onclick: () => confirm("Make a new picture for every moment? Each picture costs about $0.01.") && run(true) }, "Redo all pictures")
        : null,
    ),
  );
}

function picturesSection(project) {
  const analysis = project.analysis;
  if (!analysis) return section("Pictures", el("p", { class: "muted" }, "Not planned yet."));
  const entities = analysis.entities.length
    ? el(
        "div",
        { class: "entities" },
        analysis.entities.map((entity) =>
          el(
            "div",
            { class: "entity", title: entity.description },
            entity.ref_key ? el("img", { src: mediaUrl(project.id, entity.ref_key), alt: "" }) : el("div", { class: "thumb-empty" }, entity.kind[0].toUpperCase()),
            el("div", {}, el("strong", {}, entity.name), el("small", { class: "muted" }, entity.ref_source === "video" ? "from your video" : entity.ref_source === "generated" ? "reference drawn" : entity.kind)),
          ),
        ),
      )
    : null;
  const moments = analysis.moments.length
    ? el("ol", { class: "moments" }, analysis.moments.map((moment) => momentCard(project, moment)))
    : el("p", { class: "muted" }, project.style.visuals === "off" ? "Pictures are off for this reel." : "No moments were planned.");
  return section(
    "Pictures",
    analysis.summary ? el("p", { class: "muted small" }, analysis.summary) : null,
    entities,
    moments,
  );
}

function momentCard(project, moment) {
  const prompt = el("textarea", { rows: 3, maxlength: 1200 }, moment.prompt);
  const display = el(
    "select",
    {
      onchange: (e) => act(() => api.patch(`/api/projects/${project.id}/moments/${moment.id}`, { display: e.target.value }), "Making a picture in the new shape…"),
    },
    options("display", ["overlay", "cutout", "cutaway"], moment.display),
  );
  const enabled = el("input", {
    type: "checkbox",
    checked: moment.enabled,
    onchange: (e) => act(() => api.patch(`/api/projects/${project.id}/moments/${moment.id}`, { enabled: e.target.checked })),
  });
  const regenerate = () => {
    const text = prompt.value.trim();
    act(
      () => api.post(`/api/projects/${project.id}/moments/${moment.id}/regenerate`, text && text !== moment.prompt ? { prompt: text } : {}),
      "Regenerating the picture…",
    );
  };
  const picture = moment.asset
    ? el("a", { href: mediaUrl(project.id, moment.asset.key), target: "_blank", rel: "noopener" }, el("img", { src: mediaUrl(project.id, moment.asset.key), alt: moment.prompt, loading: "lazy" }))
    : el("div", { class: "thumb-empty big" }, moment.error ? "!" : "…");
  return el(
    "li",
    { class: `moment${moment.enabled ? "" : " off"}` },
    el("div", { class: `moment-picture ${moment.display}` }, picture),
    el(
      "div",
      { class: "moment-body" },
      el("div", { class: "moment-head" }, el("span", { class: "time" }, `${seconds(moment.start)} – ${seconds(moment.end)}`), el("label", { class: "toggle" }, enabled, " show")),
      el("p", { class: "quote" }, "“", moment.quote, "”"),
      moment.note ? el("p", { class: "note" }, moment.note) : null,
      moment.error ? el("p", { class: "banner error small" }, moment.error) : null,
      field("Shown as", display),
      el("details", {}, el("summary", {}, "Picture prompt"), prompt, el("button", { class: "btn small", onclick: regenerate }, "Regenerate")),
    ),
  );
}

function transcriptSection(project) {
  const transcript = project.transcript;
  if (!transcript) return null;
  if (!transcript.turns.length) return section("Captions", el("p", { class: "muted" }, "No speech was recognised, so the reel has no captions."));
  return section(
    "Captions",
    el("p", { class: "muted small" }, "Fix any word Muse Voice Transcribe misheard. Words are re-timed over the same speech."),
    el(
      "ol",
      { class: "turns" },
      transcript.turns.map((turn) => {
        const text = el("textarea", {
          rows: Math.min(5, Math.ceil(turn.text.length / 60)),
          maxlength: 2000,
          onchange: (e) => {
            const value = e.target.value.trim();
            if (value && value !== turn.text) act(() => api.put(`/api/projects/${project.id}/turns/${turn.id}`, { text: value }), "Caption updated");
          },
        }, turn.text);
        return el("li", { class: "turn" }, el("span", { class: "time" }, seconds(turn.start)), text, turn.text !== turn.original ? el("small", { class: "muted" }, "heard: ", turn.original) : null);
      }),
    ),
  );
}

// ---- rendering -----------------------------------------------------------------------------

function renderSection(project) {
  const fit = el("input", { type: "checkbox" });
  const go = () => act(() => api.post(`/api/projects/${project.id}/render`, { fit_mb: fit.checked ? 25 : null }), "Rendering…");
  const renders = [...project.renders].reverse();
  return section(
    "Reel",
    el("label", { class: "toggle" }, fit, " Keep under 25 MB (for Messenger and Instagram DMs)"),
    el("button", { class: "btn primary wide", onclick: go }, renders.length ? "Render again" : "Render the reel"),
    renders.map((r, i) =>
      el(
        "div",
        { class: "render" },
        i === 0 ? el("video", { src: mediaUrl(project.id, r.key), controls: true, playsinline: true, preload: "metadata" }) : null,
        el(
          "div",
          { class: "render-info" },
          el("span", {}, `${seconds(r.duration)} · ${megabytes(r.size)}${r.fit_mb ? ` · ≤${r.fit_mb} MB` : ""}`),
          el("small", { class: "muted" }, ago(r.created_at)),
          el("a", { class: "btn small", href: mediaUrl(project.id, r.key, { download: true }) }, "Download"),
        ),
      ),
    ),
  );
}

function usageSection(project) {
  const u = project.usage;
  const rows = [
    ["Text model", `${u.spark_input_tokens.toLocaleString()} in · ${u.spark_output_tokens.toLocaleString()} out tokens`],
    ["Muse Image", `${u.images} image${u.images === 1 ? "" : "s"}`],
    ["SAM 3.1", `${u.sam_images} image${u.sam_images === 1 ? "" : "s"}`],
    ["Voice Transcribe", seconds(u.asr_seconds)],
  ];
  return section(
    "Model API usage",
    el("dl", { class: "usage" }, rows.map(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
    el("p", { class: "muted small" }, `About $${u.estimated_usd.toFixed(3)} at list prices (estimate).`),
    el(
      "button",
      { class: "btn danger small", onclick: () => confirm("Delete this reel and all its files?") && act(async () => {
          await api.del(`/api/projects/${project.id}`);
          location.hash = "#/";
          return null;
        }, "Deleted") },
      "Delete reel",
    ),
  );
}

// ---- your Model API key ---------------------------------------------------------------------

function updateKeyButton() {
  const button = document.getElementById("key-button");
  button.hidden = false;
  const hint = apiKey.hint();
  button.textContent = hint ? `API key ${hint}` : "Add API key";
  button.className = `key-button ${hint ? "ok" : "warn"}`;
}

function openKeyDialog(reason) {
  if (document.querySelector(".modal.key-dialog")) return;
  const root = document.getElementById("modal-root");
  const input = el("input", { type: "password", autocomplete: "off", spellcheck: "false", placeholder: "LLM|…", "aria-label": "Model API key" });
  const status = el("div", { class: "key-status", "aria-live": "polite" });
  const save = el("button", { class: "btn primary" }, "Check and save");
  const close = () => {
    document.removeEventListener("keydown", onKey);
    modal.remove();
  };
  const onKey = (event) => event.key === "Escape" && close();
  const check = async () => {
    const key = input.value.trim();
    if (!key) return input.focus();
    save.disabled = true;
    clear(status).append(el("span", { class: "muted" }, "Asking Meta which models this key can use…"));
    try {
      const result = await api.checkKey(key);
      apiKey.set(key);
      updateKeyButton();
      clear(status).append(
        el("p", { class: "ok-text" }, `Key saved in this browser. It can use ${result.models.length} models.`),
        result.missing.length ? el("p", { class: "banner warn small" }, `Not listed for this key: ${result.missing.join(", ")}. Jobs that need them may fail.`) : null,
      );
      toast("API key saved", "ok");
      if (state.project) render();
      setTimeout(close, result.missing.length ? 4000 : 900);
    } catch (error) {
      clear(status).append(el("p", { class: "banner error small" }, error.message));
    } finally {
      save.disabled = false;
    }
  };
  save.addEventListener("click", check);
  input.addEventListener("keydown", (event) => event.key === "Enter" && check());
  const forget = apiKey.get()
    ? el("button", {
        class: "btn danger small",
        onclick: () => {
          apiKey.clear();
          updateKeyButton();
          toast("API key removed from this browser", "ok");
          close();
          if (state.project) render();
        },
      }, "Forget key")
    : null;
  const modal = el(
    "div",
    { class: "modal key-dialog", role: "dialog", "aria-modal": "true", "aria-label": "Model API key" },
    el(
      "div",
      { class: "modal-card" },
      el("div", { class: "modal-head" }, el("h2", {}, "Your Meta Model API key"), el("button", { class: "icon-btn", "aria-label": "Close", onclick: close }, "✕")),
      reason ? el("p", { class: "banner warn small" }, reason) : null,
      el("p", { class: "muted small" }, "Each person uses their own key, and the Model API usage is billed to it. Create one in the ", el("a", { href: "https://dev.meta.ai/", target: "_blank", rel: "noopener" }, "Model API dashboard"), "."),
      apiKey.get() ? el("p", { class: "small" }, `Saved key: ${apiKey.hint()}`) : null,
      field("API key", input),
      status,
      el("div", { class: "row" }, save, forget),
      el("p", { class: "muted small" }, "The key stays in this browser. It is sent to the studio's server only with actions that start a job, held in memory until that job ends, and never written to disk or logs."),
    ),
  );
  modal.addEventListener("click", (event) => event.target === modal && close());
  document.addEventListener("keydown", onKey);
  root.append(modal);
  input.focus();
}

// ---- start --------------------------------------------------------------------------------

async function boot() {
  try {
    state.config = await api.get("/api/config");
  } catch (error) {
    clear(app).append(el("p", { class: "banner error" }, error.message));
    return;
  }
  document.getElementById("key-button").addEventListener("click", () => openKeyDialog());
  updateKeyButton();
  start();
}

boot();
