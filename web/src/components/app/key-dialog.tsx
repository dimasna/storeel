import { useState } from "react";
import { api, apiKey, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Field, Input, Banner } from "@/components/ui/primitives";

export function KeyDialog({
  open,
  reason,
  onClose,
}: {
  open: boolean;
  reason?: string;
  onClose: () => void;
}) {
  const [value, setValue] = useState("");
  const [status, setStatus] = useState<{ tone: "info" | "ok" | "error"; text: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const { toast } = useToast();
  const saved = apiKey.hint();

  const check = async () => {
    const key = value.trim();
    if (!key) return;
    setChecking(true);
    setStatus({ tone: "info", text: "Asking which models this key can use…" });
    try {
      const result = await api.checkKey(key);
      apiKey.set(key);
      toast("API key saved", "ok");
      setStatus({
        tone: "ok",
        text: `Key saved in this browser. It can use ${result.models.length} models.${
          result.missing.length ? ` Not listed: ${result.missing.join(", ")}.` : ""
        }`,
      });
      window.setTimeout(onClose, result.missing.length ? 2500 : 800);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not verify the key.";
      setStatus({ tone: "error", text: msg });
    } finally {
      setChecking(false);
    }
  };

  const forget = () => {
    apiKey.clear();
    toast("API key removed from this browser", "ok");
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title="Your Muse / Model API key">
      <div className="flex flex-col gap-4">
        {reason ? <Banner tone="warn">{reason}</Banner> : null}
        <p className="text-sm text-muted-foreground">
          Each person uses their own key, and Model API usage is billed to it. Create one in the{" "}
          <a
            href="https://dev.meta.ai/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline-offset-2 hover:underline"
          >
            Model API dashboard
          </a>
          .
        </p>
        {saved ? <p className="text-sm text-foreground">Saved key: {saved}</p> : null}
        <Field label="API key">
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="LLM|…"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && check()}
          />
        </Field>
        {status ? <Banner tone={status.tone === "info" ? "info" : status.tone === "ok" ? "info" : "error"}>{status.text}</Banner> : null}
        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Check and save"}
          </Button>
          {saved ? (
            <Button variant="danger" size="sm" onClick={forget}>
              Forget key
            </Button>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground/80">
          The key stays in this browser. It is sent to the server only with actions that start a
          job, held in memory until that job ends, and never written to disk or logs.
        </p>
      </div>
    </Modal>
  );
}
