import { useState } from "react";
export default function PilotBankHeldOut({ attempt, bank, base }) {
  const [open, setOpen] = useState(false);
  const pinned = bank.exports.find(
    (item) =>
      String(item.revision) === String(attempt.export_revision) &&
      item.manifest_sha256 === attempt.manifest_sha256,
  );
  const images = (pinned?.entries || []).filter(
    (entry) => entry.role === "evaluation",
  );
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer text-sm">
        Compare held-out photos
      </summary>
      <p className="text-sm text-content-muted">
        Review only; never sent as generation inputs. These photos belong to
        this attempt’s exact export snapshot.
      </p>
      {!pinned ? (
        <p role="status" className="text-sm">
          The pinned export is unavailable. Reload the bank to check its saved
          evidence.
        </p>
      ) : images.length === 0 ? (
        <p className="text-sm text-content-muted">
          This export contains no held-out evaluation photos.
        </p>
      ) : (
        open && (
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
            {images.map((entry) => {
              const query = new URLSearchParams({
                manifest_sha256: attempt.manifest_sha256,
              });
              const path = entry.image_path
                .split("/")
                .map(encodeURIComponent)
                .join("/");
              const url = `${base}/exports/${encodeURIComponent(attempt.export_revision)}/files/${path}?${query}`;
              return (
                <figure key={entry.image_path} className="m-0 min-w-0">
                  <img
                    src={url}
                    alt={`Held-out evaluation photo ${entry.image_id ?? entry.image_path}`}
                    className="max-h-80 max-w-full object-contain"
                  />
                  <figcaption className="text-sm break-all">
                    {entry.caption || entry.image_path}
                    <br />
                    SHA-256: {entry.image_sha256}
                  </figcaption>
                </figure>
              );
            })}
          </div>
        )
      )}
    </details>
  );
}
