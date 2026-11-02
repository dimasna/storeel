// Typed wrappers around the studio's HTTP API. Same contract as the previous vanilla client:
// the user's Muse / Model API key lives in this browser only and travels as X-Model-Api-Key on
// the requests that start a job; the server holds it in memory for that job and never stores it.

import type {
  Config,
  Novel,
  NovelSummary,
  Project,
  ProjectSummary,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const KEY_STORAGE = "storeel.modelApiKey";
const listeners = new Set<() => void>();

export const apiKey = {
  get: () => localStorage.getItem(KEY_STORAGE) || "",
  set: (value: string) => {
    localStorage.setItem(KEY_STORAGE, value.trim());
    listeners.forEach((l) => l());
  },
  clear: () => {
    localStorage.removeItem(KEY_STORAGE);
    listeners.forEach((l) => l());
  },
  hint: () => {
    const key = localStorage.getItem(KEY_STORAGE) || "";
    return key ? `…${key.slice(-4)}` : "";
  },
  subscribe: (fn: () => void) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

type Detail = { detail?: string | { loc?: string[]; msg: string }[]; code?: string } | null;

function detailText(data: Detail): string {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d) => `${(d.loc || []).slice(1).join(".") || "input"}: ${d.msg}`)
      .join("; ");
  }
  return "";
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  key: string = apiKey.get(),
): Promise<T> {
  const options: RequestInit = { method, headers: { Accept: "application/json" } };
  const headers = options.headers as Record<string, string>;
  if (method !== "GET" && key) headers["X-Model-Api-Key"] = key;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, "The studio server is not reachable.");
  }
  if (response.status === 204) return null as T;
  let data: (Detail & Record<string, unknown>) | null = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, detailText(data) || response.statusText, data?.code || null);
  }
  return data as T;
}

export const api = {
  getConfig: () => request<Config>("GET", "/api/config"),
  checkKey: (key: string) =>
    request<{ ok: boolean; models: string[]; missing: string[] }>("POST", "/api/key/check", {}, key),

  // Projects
  listProjects: () => request<ProjectSummary[]>("GET", "/api/projects"),
  createProject: (path: "video" | "idea", title?: string) =>
    request<Project>("POST", "/api/projects", { path, ...(title ? { title } : {}) }),
  getProject: (id: string) => request<Project>("GET", `/api/projects/${id}`),
  renameProject: (id: string, title: string) =>
    request<Project>("PATCH", `/api/projects/${id}`, { title }),
  deleteProject: (id: string) => request<null>("DELETE", `/api/projects/${id}`),

  // Clips (path A)
  deleteClip: (id: string, clipId: string) =>
    request<Project>("DELETE", `/api/projects/${id}/clips/${clipId}`),
  orderClips: (id: string, ids: string[]) =>
    request<Project>("PUT", `/api/projects/${id}/clips/order`, { ids }),

  // Style
  setStyle: (id: string, style: Record<string, unknown>) =>
    request<Project>("PUT", `/api/projects/${id}/style`, style),

  // Idea / script (path B)
  setIdea: (id: string, idea: Record<string, unknown>) =>
    request<Project>("PUT", `/api/projects/${id}/idea`, idea),
  setScript: (id: string, script: Record<string, unknown>) =>
    request<Project>("PUT", `/api/projects/${id}/script`, script),
  deleteTake: (id: string, sceneId: string) =>
    request<Project>("DELETE", `/api/projects/${id}/scenes/${sceneId}/take`),

  // Processing / review
  process: (id: string, fresh: boolean) =>
    request<Project>("POST", `/api/projects/${id}/process`, { fresh }),
  editTurn: (id: string, turnId: number, text: string) =>
    request<Project>("PUT", `/api/projects/${id}/turns/${turnId}`, { text }),
  editMoment: (id: string, momentId: string, body: { enabled?: boolean; display?: string }) =>
    request<Project>("PATCH", `/api/projects/${id}/moments/${momentId}`, body),
  regenerateMoment: (id: string, momentId: string, prompt?: string) =>
    request<Project>(
      "POST",
      `/api/projects/${id}/moments/${momentId}/regenerate`,
      prompt ? { prompt } : {},
    ),

  // Render / jobs
  render: (id: string, fitMb: number | null) =>
    request<Project>("POST", `/api/projects/${id}/render`, { fit_mb: fitMb }),
  cancelJob: (jobId: string) => request<Project>("POST", `/api/jobs/${jobId}/cancel`),

  // Novels (path C)
  listNovels: () => request<NovelSummary[]>("GET", "/api/novels"),
  createNovel: (fields: Record<string, unknown>) => request<Novel>("POST", "/api/novels", fields),
  getNovel: (id: string) => request<Novel>("GET", `/api/novels/${id}`),
  editNovel: (id: string, fields: Record<string, unknown>) =>
    request<Novel>("PUT", `/api/novels/${id}`, fields),
  deleteNovel: (id: string) => request<null>("DELETE", `/api/novels/${id}`),
  addChapter: (id: string, body: { text: string; title: string; number: number | null }) =>
    request<Novel>("POST", `/api/novels/${id}/chapters`, body),
  deleteChapter: (id: string, number: number) =>
    request<Novel>("DELETE", `/api/novels/${id}/chapters/${number}`),
  openChapterReel: (id: string, number: number) =>
    request<Project>("POST", `/api/novels/${id}/chapters/${number}/reel`),

  // Novel parts (path C reels)
  writePart: (id: string, fromVideo: boolean) =>
    request<Project>("POST", `/api/projects/${id}/story`, { from_video: fromVideo }),
  editPart: (id: string, body: Record<string, unknown>) =>
    request<Project>("PUT", `/api/projects/${id}/story`, body),
};

// Multipart upload with progress (fetch cannot report upload progress).
export function upload(
  path: string,
  file: Blob,
  filename: string,
  onProgress?: (fraction: number) => void,
): Promise<Project> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, filename);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.responseType = "json";
    const key = apiKey.get();
    if (key) xhr.setRequestHeader("X-Model-Api-Key", key);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Project);
      else
        reject(
          new ApiError(xhr.status, detailText(xhr.response) || `Upload failed (${xhr.status})`),
        );
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed: the server is not reachable"));
    xhr.send(form);
  });
}

export function mediaUrl(projectId: string, key: string, download = false): string {
  const path = key.split("/").map(encodeURIComponent).join("/");
  return `/api/projects/${projectId}/media/${path}${download ? "?download=1" : ""}`;
}

export function novelMediaUrl(novelId: string, key: string): string {
  const path = key.split("/").map(encodeURIComponent).join("/");
  return `/api/novels/${novelId}/media/${path}`;
}
