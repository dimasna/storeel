import { useEffect, useRef, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Banner } from "@/components/ui/primitives";

const TYPES = [
  "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
  "video/mp4",
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
];

function pickType(): string | null {
  if (!window.MediaRecorder) return null;
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

type Phase = "idle" | "countdown" | "recording" | "review" | "uploading";

export interface RecorderScene {
  id: string;
  lines: string;
  direction: string;
  purpose?: string;
}

export function Recorder({
  scene,
  index,
  total,
  onTake,
  onClose,
}: {
  scene: RecorderScene;
  index: number;
  total: number;
  onTake: (blob: Blob, name: string, onProgress: (f: number) => void) => Promise<void>;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(3);
  const [elapsed, setElapsed] = useState(0);
  const [uploadPct, setUploadPct] = useState(0);
  const [reviewUrl, setReviewUrl] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const typeRef = useRef<string>("");
  const timerRef = useRef<number | null>(null);
  const startedRef = useRef(0);
  const closedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const type = pickType();
    if (type === null) {
      setError("This browser cannot record video. Try a recent Chrome, Edge, Firefox or Safari, or upload a file.");
      return;
    }
    if (!window.isSecureContext) {
      setError("The camera needs a secure page: open the studio over https.");
      return;
    }
    typeRef.current = type;
    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1920 } },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      .then((stream) => {
        if (cancelled || closedRef.current) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      })
      .catch((e: Error) => {
        if (!cancelled)
          setError(`Camera or microphone not available: ${e.message || e.name}. Allow access and try again.`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      closedRef.current = true;
      if (timerRef.current) window.clearInterval(timerRef.current);
      recorderRef.current?.state !== "inactive" && recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (reviewUrl) URL.revokeObjectURL(reviewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-attach stream to the preview element when returning from review to idle.
  useEffect(() => {
    if ((phase === "idle" || phase === "countdown" || phase === "recording") && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [phase]);

  const startCountdown = () => {
    if (!streamRef.current) return;
    setPhase("countdown");
    let left = 3;
    setCount(left);
    timerRef.current = window.setInterval(() => {
      left -= 1;
      if (left > 0) setCount(left);
      else {
        if (timerRef.current) window.clearInterval(timerRef.current);
        startRecording();
      }
    }, 800);
  };

  const startRecording = () => {
    chunksRef.current = [];
    const options: MediaRecorderOptions = {
      videoBitsPerSecond: 8_000_000,
      audioBitsPerSecond: 128_000,
    };
    if (typeRef.current) options.mimeType = typeRef.current;
    const rec = new MediaRecorder(streamRef.current!, options);
    rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
    rec.onstop = () => {
      const blob = new Blob(chunksRef.current, {
        type: rec.mimeType || typeRef.current || "video/webm",
      });
      const url = URL.createObjectURL(blob);
      setReviewUrl(url);
      blobRef.current = blob;
      setPhase("review");
    };
    rec.start(1000);
    recorderRef.current = rec;
    startedRef.current = performance.now();
    setPhase("recording");
    setElapsed(0);
    timerRef.current = window.setInterval(
      () => setElapsed((performance.now() - startedRef.current) / 1000),
      100,
    );
  };

  const blobRef = useRef<Blob | null>(null);

  const stopRecording = () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
  };

  const retake = () => {
    if (reviewUrl) URL.revokeObjectURL(reviewUrl);
    setReviewUrl(null);
    blobRef.current = null;
    setPhase("idle");
  };

  const use = async () => {
    if (!blobRef.current) return;
    const ext = (blobRef.current.type || "").includes("mp4") ? "mp4" : "webm";
    setPhase("uploading");
    try {
      await onTake(blobRef.current, `${scene.id}-take.${ext}`, (f) => setUploadPct(Math.round(f * 100)));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("review");
    }
  };

  const reviewing = phase === "review" || phase === "uploading";

  return (
    <Modal
      open
      onClose={onClose}
      dismissable={phase !== "uploading"}
      title={`Scene ${index + 1} of ${total}${scene.purpose ? ` · ${scene.purpose}` : ""}`}
      className="max-w-md"
    >
      <div className="flex flex-col gap-4">
        {error ? <Banner tone="error">{error}</Banner> : null}

        <div className="relative mx-auto aspect-[9/16] w-full max-w-[280px] overflow-hidden rounded-2xl bg-black">
          {reviewing ? (
            <video src={reviewUrl ?? undefined} controls playsInline autoPlay className="size-full object-cover" />
          ) : (
            <>
              <video ref={videoRef} muted playsInline autoPlay className="size-full scale-x-[-1] object-cover" />
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-3 text-center">
                <p className="text-sm font-medium text-white">{scene.lines}</p>
                {scene.direction ? (
                  <p className="mt-1 text-xs text-white/70">{scene.direction}</p>
                ) : null}
              </div>
              {phase === "countdown" ? (
                <div className="absolute inset-0 grid place-items-center text-6xl font-bold text-white">
                  {count}
                </div>
              ) : null}
              {phase === "recording" ? (
                <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs font-medium text-white">
                  <span className="size-2 animate-pulse rounded-full bg-danger" />
                  REC {elapsed.toFixed(1)}s
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="flex items-center justify-center gap-3">
          {phase === "idle" && (
            <Button variant="primary" size="lg" onClick={startCountdown} disabled={!streamRef.current && !error}>
              ● Record
            </Button>
          )}
          {phase === "countdown" && <span className="text-sm text-muted-foreground">Get ready…</span>}
          {phase === "recording" && (
            <Button variant="danger" size="lg" onClick={stopRecording}>
              ■ Stop
            </Button>
          )}
          {phase === "review" && (
            <>
              <Button onClick={retake}>↺ Retake</Button>
              <Button variant="primary" onClick={use}>
                Use this take
              </Button>
            </>
          )}
          {phase === "uploading" && (
            <div className="w-full">
              <div className="h-2 overflow-hidden rounded-full bg-border-strong">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${uploadPct}%` }} />
              </div>
              <p className="mt-1 text-center text-xs text-muted-foreground">Uploading the take…</p>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
