/** Persistent reminder that eval surfaces are not live ops. */

type Props = {
  /** Extra line under the snapshot label (e.g. FAILED vs scored miss). */
  note?: string;
};

export function EvalSnapshotBanner({ note }: Props) {
  return (
    <aside className="eval-banner" role="note" aria-label="Evaluation context">
      <strong className="eval-banner-label">Immutable snapshot</strong>
      <span className="eval-banner-body">
        Evaluation surface — not a live ops incident. GroundTruth is
        evaluator-only and never linked from Ops Incident Detail.
      </span>
      {note ? <span className="eval-banner-note">{note}</span> : null}
    </aside>
  );
}
