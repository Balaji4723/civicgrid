"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  Loader2,
  LocateFixed,
  Lock,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";
import { Notice } from "./ui";

export interface CaptureResult {
  file: File;
  dataUrl: string;
  gps: { lat: number; lng: number; accuracy: number } | null;
  timestamp: string;
}

type Phase = "idle" | "requesting" | "preview" | "captured" | "denied" | "insecure";

interface Props {
  /** Label shown on the trigger button */
  label?: string;
  /** Called once user confirms the capture */
  onCapture: (result: CaptureResult) => void;
  /** Optional: overrides the trigger button entirely */
  triggerClassName?: string;
  /** Whether to auto-acquire GPS after capture */
  withGps?: boolean;
}

/**
 * CameraCapture — opens the rear device camera via getUserMedia, lets the
 * user preview a live stream, captures a JPEG snapshot to canvas, allows
 * retake / confirm, and optionally acquires GPS coordinates automatically.
 *
 * Designed for reliable operation on mobile devices (rear camera preferred)
 * and desktop laptops/webcams with full graceful fallback.
 */
export function CameraCapture({ label = "Open Camera", onCapture, withGps = true }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [capturedUrl, setCapturedUrl] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [gps, setGps] = useState<{ lat: number; lng: number; accuracy: number } | null>(null);
  const [gpsState, setGpsState] = useState<"idle" | "acquiring" | "ok" | "denied">("idle");
  const [err, setErr] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch {
          // ignore
        }
      });
      streamRef.current = null;
    }
  }, []);

  // Cleanup stream on unmount
  useEffect(() => () => stopStream(), [stopStream]);

  // Robust stream attachment to video element whenever entering preview phase
  useEffect(() => {
    if (phase === "preview" && videoRef.current && streamRef.current) {
      const video = videoRef.current;
      video.srcObject = streamRef.current;
      const playPromise = video.play();
      if (playPromise !== undefined) {
        playPromise.catch((e) => {
          console.warn("Video autoplay prevented by browser policy:", e);
        });
      }
    }
  }, [phase]);

  async function acquireMediaStream(): Promise<MediaStream> {
    if (typeof window === "undefined") {
      throw new Error("WINDOW_UNDEFINED");
    }

    // Check secure context
    if (window.isSecureContext === false && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
      throw new Error("INSECURE_CONTEXT");
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("MEDIA_DEVICES_NOT_SUPPORTED");
    }

    // Attempt 1: Ideal rear/environment camera with 1280x960
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 960 },
        },
        audio: false,
      });
    } catch (err1) {
      console.warn("High-res environment facing camera request failed, trying flexible facingMode:", err1);
    }

    // Attempt 2: Flexible rear/environment camera
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
    } catch (err2) {
      console.warn("Flexible facingMode failed, falling back to any available camera:", err2);
    }

    // Attempt 3: Any available camera (desktop webcam / default)
    return await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false,
    });
  }

  async function openCamera() {
    setErr(null);
    setPhase("requesting");
    setCapturedUrl(null);
    setCapturedFile(null);
    setGps(null);
    setGpsState("idle");

    try {
      const stream = await acquireMediaStream();
      streamRef.current = stream;
      setPhase("preview");
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message;
      const name = (e as { name?: string })?.name;

      if (msg === "INSECURE_CONTEXT" || (!window.isSecureContext && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1")) {
        setPhase("insecure");
        return;
      }

      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setPhase("denied");
      } else if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        setPhase("idle");
        setErr("No camera hardware found on this device. Please ensure a camera is connected.");
      } else if (name === "NotReadableError" || name === "TrackStartError") {
        setPhase("idle");
        setErr("Camera is already in use by another application. Please close other apps using the camera and try again.");
      } else {
        setPhase("idle");
        setErr("Unable to start camera preview. Please check device permissions and secure HTTPS connection.");
      }
    }
  }

  function capture() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 960;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, w, h);

    const dataUrl = canvas.toDataURL("image/jpeg", 0.88);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const ts = new Date().toISOString().replace(/[:.]/g, "-");
        const file = new File([blob], `civicgrid-capture-${ts}.jpg`, { type: "image/jpeg" });
        setCapturedFile(file);
      },
      "image/jpeg",
      0.88
    );

    stopStream();
    setCapturedUrl(dataUrl);
    setPhase("captured");

    if (withGps) {
      acquireGps();
    }
  }

  function acquireGps() {
    if (!navigator.geolocation) {
      setGpsState("denied");
      return;
    }
    setGpsState("acquiring");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGps({
          lat: +pos.coords.latitude.toFixed(6),
          lng: +pos.coords.longitude.toFixed(6),
          accuracy: pos.coords.accuracy,
        });
        setGpsState("ok");
      },
      () => setGpsState("denied"),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  function retake() {
    stopStream();
    setCapturedUrl(null);
    setCapturedFile(null);
    setGps(null);
    setGpsState("idle");
    setErr(null);
    openCamera();
  }

  function dismiss() {
    stopStream();
    setCapturedUrl(null);
    setCapturedFile(null);
    setGps(null);
    setGpsState("idle");
    setPhase("idle");
    setErr(null);
  }

  function confirm() {
    if (!capturedFile || !capturedUrl) return;
    onCapture({
      file: capturedFile,
      dataUrl: capturedUrl,
      gps: gps,
      timestamp: new Date().toISOString(),
    });
    dismiss();
  }

  // ---- render ----

  if (phase === "insecure") {
    return (
      <div className="rounded-xl border border-flag-200 bg-flag-50 p-4 space-y-3">
        <div className="flex items-start gap-3">
          <Lock className="h-5 w-5 text-flag-600 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-bold text-flag-800">Secure HTTPS Connection Required</p>
            <p className="mt-1 text-xs text-flag-700 leading-relaxed">
              Mobile browsers require a secure HTTPS connection to access the physical device camera over Wi-Fi.
            </p>
          </div>
        </div>
        <div className="rounded-lg bg-flag-100/80 p-3 text-xs text-flag-900 space-y-1.5">
          <p className="font-semibold">How to connect with camera support:</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>Ensure the frontend was started with HTTPS (e.g. <code className="bg-white/80 px-1 py-0.5 rounded font-mono">npm run dev:https</code>).</li>
            <li>Open the URL with <code className="bg-white/80 px-1 py-0.5 rounded font-mono">https://</code> in your mobile browser.</li>
            <li>Accept the local development certificate prompt and tap &quot;Allow&quot; for camera.</li>
          </ol>
        </div>
        <button
          type="button"
          onClick={openCamera}
          className="inline-flex items-center gap-2 text-xs font-semibold text-flag-800 underline underline-offset-2"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry Connection
        </button>
      </div>
    );
  }

  if (phase === "idle") {
    return (
      <div className="space-y-2">
        <button
          type="button"
          onClick={openCamera}
          className="inline-flex w-full items-center justify-center gap-2.5 rounded-xl border-2 border-dashed border-track-300 bg-track-50 px-5 py-4 text-sm font-semibold text-track-700 transition-all hover:bg-track-100 hover:border-track-400 active:scale-98 min-h-[56px]"
        >
          <Camera className="h-5 w-5 shrink-0" />
          {label}
        </button>
        {err && (
          <Notice tone="flag" title="Camera Notice">
            {err}
          </Notice>
        )}
      </div>
    );
  }

  if (phase === "denied") {
    return (
      <div className="rounded-xl border border-flag-200 bg-flag-50 p-4 space-y-3">
        <div className="flex items-start gap-3">
          <ShieldAlert className="h-5 w-5 text-flag-600 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-bold text-flag-700">Camera permission denied</p>
            <p className="mt-1 text-xs text-flag-700 leading-relaxed">
              CivicGrid requires direct camera access to capture field evidence. There is no
              file-upload alternative — photo evidence must be captured on-device.
            </p>
          </div>
        </div>
        <div className="rounded-lg bg-flag-100 p-3 text-xs text-flag-800 space-y-1">
          <p className="font-semibold">To enable camera access:</p>
          <ol className="list-decimal list-inside space-y-0.5">
            <li>Tap the site settings / lock icon in your browser address bar.</li>
            <li>Find &quot;Camera&quot; and set it to &quot;Allow&quot;.</li>
            <li>Reload the page and try again.</li>
          </ol>
        </div>
        <button
          type="button"
          onClick={openCamera}
          className="inline-flex items-center gap-2 text-xs font-semibold text-flag-700 underline underline-offset-2"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Try again
        </button>
      </div>
    );
  }

  if (phase === "requesting") {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-line bg-paper p-6 text-sm text-ink-soft">
        <Loader2 className="h-5 w-5 animate-spin text-track-600" />
        Requesting camera access…
      </div>
    );
  }

  if (phase === "preview") {
    return (
      <div className="space-y-3">
        <div className="relative overflow-hidden rounded-xl border border-line bg-black min-h-[240px] flex items-center justify-center">
          {/* Hidden canvas used for snapshot */}
          <canvas ref={canvasRef} className="hidden" />
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onLoadedMetadata={() => {
              videoRef.current?.play().catch(() => {});
            }}
            className="w-full max-h-80 object-contain bg-black rounded-xl"
          />
          <button
            type="button"
            onClick={dismiss}
            className="absolute top-2.5 right-2.5 rounded-full bg-ink/70 p-2 text-white hover:bg-ink/90 shadow-md z-10 transition-colors"
            aria-label="Cancel camera"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <button
          type="button"
          onClick={capture}
          className="inline-flex w-full items-center justify-center gap-2.5 rounded-xl bg-track-600 px-5 py-3.5 text-sm font-bold text-white shadow-md hover:bg-track-700 active:scale-98 transition-all min-h-[52px]"
        >
          <Camera className="h-5 w-5 shrink-0" />
          Capture Photo
        </button>
      </div>
    );
  }

  if (phase === "captured") {
    return (
      <div className="space-y-3">
        {/* Photo preview */}
        <div className="relative overflow-hidden rounded-xl border border-line bg-black min-h-[220px] flex items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={capturedUrl!}
            alt="Captured evidence photo"
            className="w-full max-h-80 object-contain bg-black rounded-xl"
          />
          <div className="absolute top-2.5 left-2.5 rounded-full bg-ok-600/90 px-3 py-1 text-xs font-bold text-white flex items-center gap-1.5 shadow-md">
            <CheckCircle2 className="h-3.5 w-3.5" /> Photo captured
          </div>
        </div>

        {/* GPS status */}
        {withGps && (
          <div className="rounded-lg border border-line bg-paper p-2.5 text-xs space-y-0.5">
            {gpsState === "acquiring" && (
              <p className="flex items-center gap-1.5 text-ink-soft">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Acquiring device GPS…
              </p>
            )}
            {gpsState === "ok" && gps && (
              <p className="flex items-center gap-1.5 text-ok-700 font-medium">
                <LocateFixed className="h-3.5 w-3.5" />
                Location captured automatically · ±{Math.round(gps.accuracy)} m
                <span className="text-ink-faint font-normal">
                  ({gps.lat.toFixed(5)}, {gps.lng.toFixed(5)})
                </span>
              </p>
            )}
            {gpsState === "denied" && (
              <p className="flex items-center gap-1.5 text-flag-700">
                <AlertCircle className="h-3.5 w-3.5" />
                GPS access denied — location will not be attached. Allow location in browser settings.
              </p>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2.5">
          <button
            type="button"
            onClick={retake}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-white px-4 py-3 text-sm font-semibold text-ink hover:bg-paper active:scale-98 transition-all min-h-[46px]"
          >
            <RefreshCw className="h-4 w-4" />
            Retake
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={!capturedFile || (withGps && gpsState === "acquiring")}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl bg-ok-600 px-4 py-3 text-sm font-bold text-white shadow-md hover:bg-ok-700 active:scale-98 disabled:opacity-50 transition-all min-h-[46px]"
          >
            <CheckCircle2 className="h-4 w-4" />
            {withGps && gpsState === "acquiring" ? "Waiting for GPS…" : "Confirm & Attach"}
          </button>
        </div>
      </div>
    );
  }

  return null;
}
