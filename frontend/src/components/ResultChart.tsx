import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QueryResult, ResultShape } from "../types";

// Bar (category) / Line (time_series). Hue accessible, grid ngang mờ, trục recessive.
// Bảng là fallback (toggle ở Message). Backend quyết định shape — component không đoán.
const NF = new Intl.NumberFormat("vi-VN");
const SERIES = ["#4f46e5", "#0891b2", "#c2410c", "#15803d"]; // khớp design, 4 hue phân biệt được
const MAX_POINTS = 40;
const AXIS = { fill: "#64748b", fontSize: 11 } as const;

export function ResultChart({
  result,
  shape,
}: {
  result: QueryResult;
  shape: ResultShape;
}) {
  const [labelCol, ...valueCols] = result.columns;
  const data = result.rows.slice(0, MAX_POINTS).map((row) => {
    const point: Record<string, unknown> = { label: String(row[0] ?? "—") };
    valueCols.forEach((name, i) => (point[name] = row[i + 1]));
    return point;
  });
  const capped = result.rows.length > MAX_POINTS;
  const Chart = shape === "time_series" ? LineChart : BarChart;

  return (
    <div>
      <div className="mb-1 text-xs text-slate-500">
        {valueCols.join(", ")} theo {labelCol}
        {capped && ` (${MAX_POINTS} dòng đầu)`}
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <Chart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 8 }}>
          <CartesianGrid vertical={false} stroke="#e2e8f0" />
          <XAxis
            dataKey="label"
            angle={shape === "time_series" ? 0 : -40}
            textAnchor={shape === "time_series" ? "middle" : "end"}
            interval={shape === "time_series" ? "preserveStartEnd" : 0}
            height={shape === "time_series" ? 32 : 64}
            tick={AXIS}
            tickLine={false}
            axisLine={{ stroke: "#cbd5e1" }}
          />
          <YAxis
            width={64}
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => NF.format(v as number)}
          />
          <Tooltip
            cursor={shape === "time_series" ? { stroke: "#cbd5e1" } : { fill: "#f1f5f9" }}
            formatter={(v) => NF.format(v as number)}
            labelStyle={{ color: "#334155" }}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
          />
          {/* Một series thì tiêu đề trên đã nêu tên — legend chỉ thêm nhiễu. */}
          {valueCols.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {valueCols.map((name, i) =>
            shape === "time_series" ? (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={SERIES[i % SERIES.length]}
                strokeWidth={2}
                dot={data.length <= 12}
                connectNulls
              />
            ) : (
              <Bar
                key={name}
                dataKey={name}
                fill={SERIES[i % SERIES.length]}
                radius={[4, 4, 0, 0]}
                maxBarSize={48}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
