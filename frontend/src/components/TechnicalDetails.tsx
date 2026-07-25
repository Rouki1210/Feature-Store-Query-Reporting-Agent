import type { RetrievedFeature, TraceItem } from "../types";

// Chi tiết cho analyst (retrieved features + pipeline trace) — collapsible.
export function TechnicalDetails({
  retrieved,
  trace,
}: {
  retrieved: RetrievedFeature[];
  trace: TraceItem[];
}) {
  if (retrieved.length === 0 && trace.length === 0) return null;
  return (
    <details className="rounded-lg border border-border bg-surface-muted text-xs">
      <summary className="cursor-pointer select-none px-3 py-2 font-medium text-text-secondary">
        Chi tiết kỹ thuật ({retrieved.length} feature · {trace.length} stage)
      </summary>
      <div className="space-y-3 border-t border-border px-3 py-2">
        {retrieved.length > 0 && (
          <div>
            <div className="mb-1 font-medium text-text-secondary">Feature được retrieve</div>
            <table className="min-w-full text-left">
              <thead className="text-text-secondary/70">
                <tr>
                  <th className="pr-3 font-normal">Tên</th>
                  <th className="pr-3 font-normal">Điểm</th>
                  <th className="font-normal">Mô tả</th>
                </tr>
              </thead>
              <tbody>
                {retrieved.map((f) => (
                  <tr key={f.name} className="align-top">
                    <td className="pr-3 font-mono text-on-surface">{f.name}</td>
                    <td className="pr-3 tabular-nums text-text-secondary">{f.score.toFixed(2)}</td>
                    <td className="text-text-secondary">{f.description_vi}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {trace.length > 0 && (
          <div>
            <div className="mb-1 font-medium text-text-secondary">Pipeline trace</div>
            <div className="space-y-1">
              {trace.map((t, i) => (
                <details key={i} className="rounded border border-border bg-surface">
                  <summary className="cursor-pointer px-2 py-1 text-text-secondary">
                    {i + 1}. {t.stage} —{" "}
                    <span className="text-text-secondary/70">{t.component}</span>{" "}
                    <span className="font-medium">[{t.status}]</span>
                  </summary>
                  <pre className="overflow-x-auto border-t border-border px-2 py-1 text-[11px] text-text-secondary">
                    {JSON.stringify({ input: t.input, output: t.output }, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}
