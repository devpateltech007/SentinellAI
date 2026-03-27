"use client";

import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from "recharts";
import type { DashboardSummary } from "@/lib/types";

interface Props {
  summary: DashboardSummary;
}

const COLORS = ["#10b981", "#ef4444", "#f59e0b", "#94a3b8"];

export default function CoverageChart({ summary }: Props) {
  const data = [
    { name: "Pass", value: summary.pass_count },
    { name: "Fail", value: summary.fail_count },
    { name: "Needs Review", value: summary.needs_review_count },
    { name: "Pending", value: summary.pending_count },
  ].filter((d) => d.value > 0);

  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-slate-200 bg-white">
        <p className="text-sm text-slate-400">No control data to display</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <h3 className="mb-4 text-sm font-semibold text-slate-700">
        Control Status Distribution
      </h3>
      <ResponsiveContainer width="100%" height={250}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={4}
            dataKey="value"
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.name}
                fill={COLORS[index % COLORS.length]}
              />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
      <div className="mt-2 text-center">
        <span className="text-2xl font-bold text-slate-900">
          {summary.evidence_coverage}%
        </span>
        <span className="ml-1 text-sm text-slate-500">evidence coverage</span>
      </div>
    </div>
  );
}
