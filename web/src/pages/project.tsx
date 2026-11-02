import { useCallback } from "react";
import { requestKey } from "@/App";
import { useProject } from "@/lib/use-project";
import { Banner } from "@/components/ui/primitives";
import { Link } from "@/lib/router";
import { ProjectView } from "@/components/app/project-view";

export function ProjectPage({ id }: { id: string }) {
  const onNeedKey = useCallback((reason?: string) => requestKey(reason), []);
  const state = useProject(id, onNeedKey);

  if (state.loading && !state.project)
    return (
      <div className="flex justify-center py-20">
        <div className="size-6 animate-spin rounded-full border-2 border-border-strong border-t-accent" />
      </div>
    );

  if (!state.project)
    return (
      <div className="flex flex-col gap-4 py-10">
        <Banner tone="error">{state.error ?? "Project not found."}</Banner>
        <Link to="/" className="text-sm text-accent hover:underline">
          ← Back to all reels
        </Link>
      </div>
    );

  return <ProjectView state={state} />;
}
