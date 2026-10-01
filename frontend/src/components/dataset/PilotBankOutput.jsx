import { usePilotBankDraft } from "./pilotBankDraft";
import PilotBankConflicts from "./PilotBankConflicts";
import PilotBankAssetEvidence from "./PilotBankAssetEvidence";
import PilotBankFields from "./PilotBankFields";
import { pilotButton, pilotInput } from "./pilotBankModel";
export default function PilotBankOutput({
  output,
  attemptId,
  base,
  tools,
  busy,
  mutate,
}) {
  const reviewState = usePilotBankDraft({
    ...(output.review || {}),
    timed: JSON.stringify(output.review?.timed_observations || [], null, 2),
  });
  const { draft: review, setDraft: setReview } = reviewState;
  const hasConflict = Object.keys(reviewState.conflicts).length > 0;
  const url = `${base}/attempts/${encodeURIComponent(attemptId)}/files/${encodeURIComponent(output.id)}`;
  const save = () => {
    if (hasConflict) return;
    const { timed, ...value } = review;
    mutate(`${url}/review`, {
      review: {
        ...value,
        correction_minutes:
          value.correction_minutes === "" || value.correction_minutes == null
            ? null
            : Number(value.correction_minutes),
        timed_observations: JSON.parse(timed),
      },
    });
  };
  return (
    <article className="min-w-0 rounded border border-border p-3 flex flex-col gap-3">
      <h4 className="m-0 text-sm font-semibold break-all">
        {output.kind} · {output.id}
      </h4>
      {output.kind === "image" && (
        <img
          src={url}
          alt="Imported manual attempt output"
          className="max-h-80 max-w-full self-start object-contain"
        />
      )}
      {output.kind === "video" && (
        <>
          <video
            src={url}
            controls
            preload="metadata"
            className="max-h-80 max-w-full"
          />
          <p className="text-sm">
            Silence:{" "}
            {output.probe?.no_audio_stream_verified
              ? "verified for this file by the server"
              : "not verified"}
            .
          </p>
          {tools.ffmpeg && (
            <button
              type="button"
              className={`${pilotButton} self-start`}
              disabled={busy}
              onClick={() => mutate(`${url}/silent`, {})}
            >
              Create silent derivative
            </button>
          )}
        </>
      )}
      <p className="m-0 text-sm break-all">
        SHA-256: {output.sha256} · {output.size} bytes
      </p>
      {["weights", "config"].includes(output.kind) && (
        <p className="text-sm break-all">
          Model: {output.model_id} · Base: {output.base_family} · Compatibility:{" "}
          {output.compatibility?.status || "unproven"} (a declaration does not
          prove compatibility).
        </p>
      )}
      <a href={url} download className="text-sm underline self-start">
        Download private file
      </a>
      {["weights", "config"].includes(output.kind) && (
        <PilotBankAssetEvidence
          output={output}
          url={url}
          busy={busy}
          mutate={mutate}
        />
      )}
      <details>
        <summary className="cursor-pointer text-sm">Review output</summary>
        <form
          className="flex flex-col gap-3 pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            try {
              save();
            } catch (error) {
              mutate(null, null, error.message);
            }
          }}
        >
          <PilotBankConflicts
            conflicts={reviewState.conflicts}
            resolve={reviewState.resolve}
          />
          <fieldset disabled={busy} className="min-w-0 flex flex-col gap-3">
            {[
              "accepted",
              "subject_recognises_likeness",
              ...(output.kind === "video" ? ["whole_clip_viewed"] : []),
            ].map((key) => (
              <label key={key} className="text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(review[key])}
                  onChange={(e) =>
                    setReview({ ...review, [key]: e.target.checked })
                  }
                />{" "}
                {
                  {
                    accepted: "Accept this output",
                    subject_recognises_likeness: "Subject recognises likeness",
                    whole_clip_viewed: "Whole clip viewed",
                  }[key]
                }
              </label>
            ))}
            <PilotBankFields
              draft={review}
              onChange={(p) => setReview({ ...review, ...p })}
              fields={[
                ["reason", "Acceptance / rejection reason", "textarea"],
                ["face_detail", "Face detail"],
                ["hands_body", "Hands / body"],
                ["prompt_adherence", "Prompt adherence"],
                ["clothing_flexibility", "Clothing flexibility"],
                ["copied_surroundings", "Copied surroundings"],
                ["composition_and_final_crop", "Composition / final crop"],
                ["correction_minutes", "Correction time (minutes)", "number"],
              ]}
            />
            {output.kind === "video" && (
              <label className="text-sm">
                Timed observations JSON (time_seconds, note)
                <textarea
                  className={pilotInput}
                  value={review.timed}
                  onChange={(e) =>
                    setReview({ ...review, timed: e.target.value })
                  }
                />
              </label>
            )}
            <button
              type="submit"
              disabled={hasConflict}
              className={`${pilotButton} self-start`}
            >
              Save output review
            </button>
          </fieldset>
        </form>
      </details>
    </article>
  );
}
