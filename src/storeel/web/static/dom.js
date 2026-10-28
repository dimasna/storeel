// A tiny DOM builder. Strings always become text nodes, so model output and user input can
// never be interpreted as HTML.

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "hidden" || key === "selected") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

export function toast(message, kind = "info") {
  const box = document.getElementById("toasts");
  const item = el("div", { class: `toast ${kind}` }, message);
  box.append(item);
  setTimeout(() => item.classList.add("leaving"), 4200);
  setTimeout(() => item.remove(), 4700);
}

export function seconds(value) {
  const total = Math.max(0, Number(value) || 0);
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return m ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${s.toFixed(1)}s`;
}

export function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export function ago(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
