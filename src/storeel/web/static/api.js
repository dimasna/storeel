// Thin wrappers around the studio's HTTP API.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailText(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d) => `${(d.loc || []).slice(1).join(".") || "input"}: ${d.msg}`)
      .join("; ");
  }
  return "";
}

async function request(method, path, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, "The studio server is not reachable. Is `storeel serve` running?");
  }
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) throw new ApiError(response.status, detailText(data) || response.statusText);
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
};

// Multipart upload with progress (fetch cannot report upload progress).
export function upload(path, file, filename, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, filename);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(new ApiError(xhr.status, detailText(xhr.response) || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed: the server is not reachable"));
    xhr.send(form);
  });
}

export function mediaUrl(projectId, key, { download = false } = {}) {
  const path = key.split("/").map(encodeURIComponent).join("/");
  return `/api/projects/${projectId}/media/${path}${download ? "?download=1" : ""}`;
}
