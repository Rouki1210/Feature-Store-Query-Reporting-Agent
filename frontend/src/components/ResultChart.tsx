import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QueryResult } from "../types";

// Bar 1 series (nhãn → số): 1 hue accessible, không legend (title nêu tên),
// grid ngang mờ, trục recessive, đầu cột bo 4px. Bảng là fallback (toggle ở ResultView).
const NF = new Intl.NumberFormat("vi-VN");
const BAR = "#4f46e5"; // primary-container (indigo) — khớp design
const MAX_BARS = 40;

export function ResultChart({ result }: { result: QueryResult }) {
  const [labelCol, valueCol] = result.columns;
  const data = result.rows.slice(0, MAX_BARS).map((r) => ({
    label: String(r[0] ?? "—"),
    value: r[1] as number,
  }));
  const capped = result.rows.length > MAX_BARS;

  return (
    <div>
      <div className="mb-1 text-xs text-slate-500">
        {valueCol} theo {labelCol}
        {capped && ` (${MAX_BARS} dòng đầu)`}
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 8 }}>
          <CartesianGrid vertical={false} stroke="#e2e8f0" />
          <XAxis
            dataKey="label"
            angle={-40}
            textAnchor="end"
            interval={0}
            height={64}
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "#cbd5e1" }}
          />
          <YAxis
            width={64}
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => NF.format(v as number)}
          />
          <Tooltip
            cursor={{ fill: "#f1f5f9" }}
            formatter={(v) => NF.format(v as number)}
            labelStyle={{ color: "#334155" }}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
          />
          <Bar dataKey="value" fill={BAR} radius={[4, 4, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
