import { useEffect, useState } from "react";
import { features, health } from "../api";
import type { FeatureSummary, HealthResponse } from "../types";
import { Icon } from "./Icon";

function HealthStrip() {
  const [h, setH] = useState<HealthResponse | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    health().then(setH).catch(() => setErr(true));
  }, []);
  const ok = !err && h?.status === "ok";
  return (
    <div className="mx-2 mb-2 rounded-lg border border-border bg-surface-muted px-3 py-2 text-[11px] text-text-secondary">
      <div className="flex items-center gap-1.5 font-medium text-text-primary">
        <span className={`h-2 w-2 rounded-full ${ok ? "bg-success" : "bg-error"}`} />
        {err ? "Mất kết nối backend" : `Backend: ${h?.status ?? "…"}`}
      </div>
      {h && (
        <div className="mt-0.5 leading-relaxed">
          {h.dialect} · {h.features_loaded} feature ·{" "}
          {h.llm_configured ? "LLM sẵn sàng" : "⚠ chưa có LLM key"}
        </div>
      )}
    </div>
  );
}

function FeatureLookup() {
  const [q, setQ] = useState("");
  const [list, setList] = useState<FeatureSummary[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const term = q.trim();
    if (!term) return setList([]);
    setLoading(true);
    const id = setTimeout(() => {
      features(term, 30).then(setList).catch(() => setList([])).finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(id);
  }, [q]);
  return (
    <div className="mt-2 flex min-h-0 flex-1 flex-col px-3">
      <div className="relative">
        <Icon name="search" className="absolute left-2 top-1.5 text-[18px] text-text-secondary" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Tra cứu feature…"
          className="w-full rounded-lg border border-border bg-surface py-1.5 pl-8 pr-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        />
      </div>
      <div className="mt-2 min-h-0 flex-1 space-y-1.5 overflow-auto pr-1">
        {loading && <div className="text-xs text-text-secondary">Đang tìm…</div>}
        {!loading && q.trim() && list.length === 0 && (
          <div className="text-xs text-text-secondary">Không có feature khớp.</div>
        )}
        {list.map((f) => (
          <div key={f.name} className="rounded-lg border border-border bg-surface p-2 text-xs">
            <div className="font-mono text-[11px] text-text-primary">{f.name}</div>
            <div className="text-text-secondary">{f.description_vi}</div>
            <div className="mt-0.5 text-[10px] uppercase tracking-wide text-text-secondary/70">
              {f.group}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const NAV = [
  { icon: "history", label: "Query History" },
  { icon: "description", label: "Technical Docs" },
  { icon: "settings", label: "System Config" },
];

export function Sidebar({ onNewQuery }: { onNewQuery: () => void }) {
  return (
    <nav className="hidden h-screen w-64 shrink-0 flex-col border-r border-border bg-surface py-6 md:flex">
      <div className="mb-8 flex items-center gap-3 px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Icon name="hub" className="text-[20px]" fill />
        </div>
        <div>
          <h1 className="text-[20px] font-bold leading-tight text-primary">AI Data Agent</h1>
          <p className="text-[12px] text-text-secondary">Feature Store Intelligence</p>
        </div>
      </div>

      <div className="mb-6 px-4">
        <button
          onClick={onNewQuery}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary-container px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
        >
          <Icon name="add" className="text-[18px]" />
          New Query
        </button>
      </div>

      <div className="flex items-center gap-3 rounded-l-lg border-r-4 border-primary bg-primary-fixed px-4 py-3 font-semibold text-primary mx-2">
        <Icon name="search" className="text-[20px]" fill />
        <span className="text-sm">Feature Lookup</span>
      </div>
      <FeatureLookup />

      <div className="mt-4 flex flex-col gap-1 px-2">
        {NAV.map((n) => (
          <button
            key={n.label}
            className="flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm text-on-surface-variant transition-colors hover:bg-surface-container hover:text-primary"
          >
            <Icon name={n.icon} className="text-[20px]" />
            {n.label}
          </button>
        ))}
      </div>

      <div className="mt-auto border-t border-border pt-4">
        <HealthStrip />
        <div className="flex flex-col gap-1 px-2">
          {[
            { icon: "help", label: "Support" },
            { icon: "account_circle", label: "Account" },
          ].map((n) => (
            <button
              key={n.label}
              className="flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm text-on-surface-variant transition-colors hover:bg-surface-container hover:text-primary"
            >
              <Icon name={n.icon} className="text-[20px]" />
              {n.label}
            </button>
          ))}
        </div>
      </div>
    </nav>
  );
}
