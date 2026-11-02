export function seconds(value: number): string {
  const total = Math.max(0, Number(value) || 0);
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return m ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${s.toFixed(1)}s`;
}

export function megabytes(bytes: number): string {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export function ago(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

/** Hours until a project is purged (24h after last update), for the "expires in" hint. */
export function expiresIn(updatedAt: string, ttlHours = 24): string {
  const elapsed = (Date.now() - new Date(updatedAt).getTime()) / 3_600_000;
  const left = ttlHours - elapsed;
  if (!Number.isFinite(left) || left <= 0) return "expiring soon";
  if (left < 1) return `expires in ${Math.max(1, Math.round(left * 60))} min`;
  return `expires in ${Math.round(left)} h`;
}
