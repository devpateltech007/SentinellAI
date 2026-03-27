"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import StatusSummaryCards from "@/components/dashboard/StatusSummaryCards";
import CoverageChart from "@/components/dashboard/CoverageChart";

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<DashboardSummary>("/dashboard/summary")
      .then(setSummary)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="text-center text-slate-500">
        Unable to load dashboard data.
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Compliance Dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Overview of control statuses, evidence coverage, and recent failures.
        </p>
      </div>

      <StatusSummaryCards summary={summary} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-4 text-lg font-semibold text-slate-800">
            Recent Failures
          </h2>
          {summary.recent_failures.length > 0 ? (
            <div className="space-y-3">
              {summary.recent_failures.map((failure) => (
                <div
                  key={failure.control_id}
                  className="rounded-lg border border-red-200 bg-red-50 p-4"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium text-red-800">
                      {failure.control_id_code}
                    </span>
                    <span className="text-xs text-red-500">
                      {new Date(failure.failed_at).toLocaleString()}
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-medium text-red-900">
                    {failure.title}
                  </p>
                  {failure.reason && (
                    <p className="mt-1 text-sm text-red-700">
                      {failure.reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-8 text-center text-sm text-emerald-700">
              No recent failures. All controls are in good standing.
            </div>
          )}
        </div>
        <div>
          <CoverageChart summary={summary} />
        </div>
      </div>
    </div>
  );
}
