"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EvidenceListResponse } from "@/lib/types";
import EvidenceList from "@/components/evidence/EvidenceList";

export default function EvidencePage() {
  const [data, setData] = useState<EvidenceListResponse | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), size: "20" });
    if (sourceFilter) params.set("source_type", sourceFilter);

    api
      .get<EvidenceListResponse>(`/evidence?${params}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, sourceFilter]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Evidence</h1>
        <p className="mt-1 text-sm text-slate-500">
          Collected evidence items from all configured sources.
        </p>
      </div>

      <div className="flex gap-3">
        {["", "github_actions", "iac_config", "app_log"].map((filter) => (
          <button
            key={filter}
            onClick={() => {
              setSourceFilter(filter);
              setPage(1);
            }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              sourceFilter === filter
                ? "bg-indigo-100 text-indigo-700"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {filter === "" ? "All" : filter.replace("_", " ")}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        </div>
      ) : (
        <>
          <EvidenceList items={data?.items ?? []} />
          {data && data.total > 20 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500">
                Showing page {data.page} of{" "}
                {Math.ceil(data.total / data.size)}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  disabled={page >= Math.ceil(data.total / data.size)}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
