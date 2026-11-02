import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Project } from "./types";
import { useToast } from "./toast";

function jobActive(project: Project | null): boolean {
  return Boolean(project?.job && ["queued", "running"].includes(project.job.status));
}

export interface UseProject {
  project: Project | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  /** Run a mutation; its returned Project becomes the new state. */
  act: (fn: () => Promise<Project | null>, success?: string) => Promise<Project | null>;
  /** Replace state directly (e.g. after an upload that already returned a Project). */
  set: (project: Project) => void;
  reload: () => void;
}

/**
 * Loads a project and keeps it fresh: while a job is queued/running it re-polls every 1.5s
 * (4s on error). Mutations go through `act`, which surfaces errors as toasts and reopens the
 * key dialog when the server reports `api_key_required`.
 */
export function useProject(id: string, onNeedKey: (reason?: string) => void): UseProject {
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const pollRef = useRef<number | null>(null);
  const idRef = useRef(id);
  idRef.current = id;

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const schedulePoll = useCallback(
    (current: Project | null, delay = 1500) => {
      stopPoll();
      if (!jobActive(current)) return;
      pollRef.current = window.setTimeout(async () => {
        const before = current;
        if (!before) return;
        let after: Project;
        try {
          after = await api.getProject(before.id);
        } catch {
          schedulePoll(before, 4000);
          return;
        }
        if (idRef.current !== before.id) return;
        setProject(after);
        const changed =
          after.job?.id !== before.job?.id || after.job?.status !== before.job?.status;
        if (changed && after.job) {
          const name = after.job.kind === "story" && after.job.step ? after.job.step : after.job.kind;
          if (after.job.status === "done") toast(`${name}: done`, "ok");
          if (after.job.status === "failed") toast(`${name} failed`, "error");
        }
        schedulePoll(after);
      }, delay);
    },
    [stopPoll, toast],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await api.getProject(idRef.current);
      setProject(p);
      schedulePoll(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [schedulePoll]);

  useEffect(() => {
    load();
    return stopPoll;
  }, [load, stopPoll, id]);

  const set = useCallback(
    (p: Project) => {
      setProject(p);
      schedulePoll(p);
    },
    [schedulePoll],
  );

  const act = useCallback(
    async (fn: () => Promise<Project | null>, success?: string) => {
      if (busy) return null;
      setBusy(true);
      try {
        const result = await fn();
        if (result && "id" in result && "stage" in result) set(result);
        if (success) toast(success, "ok");
        return result;
      } catch (e) {
        if (e instanceof ApiError && e.code === "api_key_required") {
          onNeedKey("Add your Muse / Model API key to continue.");
          return null;
        }
        toast(e instanceof Error ? e.message : String(e), "error");
        if (e instanceof ApiError && e.status === 409) load();
        return null;
      } finally {
        setBusy(false);
      }
    },
    [busy, set, toast, onNeedKey, load],
  );

  return { project, loading, error, busy, act, set, reload: load };
}

export { jobActive };
