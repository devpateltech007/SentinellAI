"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EvidenceListResponse, Project, Connector } from "@/lib/types";
import EvidenceList from "@/components/evidence/EvidenceList";

export default function EvidencePage() {
  const [data, setData] = useState<EvidenceListResponse | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [projectFilter, setProjectFilter] = useState("");

  const [projects, setProjects] = useState<Project[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), size: "20" });
    if (sourceFilter) params.set("source_type", sourceFilter);

    Promise.all([
      api.get<EvidenceListResponse>(`/evidence?${params}`),
      api.get<Project[]>("/projects"),
      api.get<Connector[]>("/connectors")
    ])
      .then(([evData, projData, connData]) => {
        setData(evData);
        setProjects(projData);
        setConnectors(connData);
      })
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

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex gap-2">
          {["", "github_actions", "iac_config", "app_log"].map((filter) => (
            <button
              key={filter}
              onClick={() => {
                if (sourceFilter !== filter || page !== 1) {
                  setLoading(true);
                  setSourceFilter(filter);
                  setPage(1);
                }
              }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                sourceFilter === filter
                  ? "bg-indigo-100 text-indigo-700"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {filter === "" ? "All Sources" : filter.replace("_", " ")}
            </button>
          ))}
        </div>

        <select
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        </div>
      ) : (
        <>
          <EvidenceList items={data?.items ?? []} projects={projects} connectors={connectors} projectFilter={projectFilter} />
          {data && data.total > 20 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500">
                Showing page {data.page} of{" "}
                {Math.ceil(data.total / data.size)}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => {
                  setLoading(true);
                  setPage((p) => p - 1);
                }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  disabled={page >= Math.ceil(data.total / data.size)}
                  onClick={() => {
                  setLoading(true);
                  setPage((p) => p + 1);
                }}
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
