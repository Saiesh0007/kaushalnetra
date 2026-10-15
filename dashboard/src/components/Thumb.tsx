import { useState } from "react";
import { thumbUrl } from "../api";

/** Blurred evidence image from the edge device. Every view is audited server-side. */
export function Thumb({ id, w = 200, onOpen }: { id: string; w?: number; onOpen?: (id: string) => void }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      className="thumb"
      src={thumbUrl(id)}
      width={w}
      height={Math.round((w * 9) / 16)}
      loading="lazy"
      alt="Privacy-blurred evidence frame"
      onError={() => setFailed(true)}
      onClick={() => onOpen?.(id)}
      style={{ cursor: onOpen ? "zoom-in" : "default" }}
    />
  );
}

export function Lightbox({ id, onClose }: { id: string | null; onClose: () => void }) {
  if (!id) return null;
  return (
    <div className="drawer-bg" onClick={onClose} style={{ display: "grid", placeItems: "center", zIndex: 3000 }}>
      <figure style={{ margin: 0, maxWidth: "92vw" }}>
        <img src={thumbUrl(id)} alt="Privacy-blurred evidence frame" style={{ maxWidth: "92vw", maxHeight: "80vh", borderRadius: 10 }} />
        <figcaption style={{ color: "#fff", fontSize: 12, marginTop: 6 }}>
          People are pixelated on the edge device before this image left the centre. This view is logged.
        </figcaption>
      </figure>
    </div>
  );
}
