"use client";

import { useEffect, useState } from "react";
import { FileBarChart } from "lucide-react";
import { api } from "@/lib/api";
import ExportButton from "@/components/reports/ExportButton";
import type { Project, ProjectDetail } from "@/lib/types";

export default function ReportsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [frameworkId, setFrameworkId] = useState("");
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(
    null,
  );

  useEffect(() => {
    api
      .get<Project[]>("/projects")
      .then(setProjects)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (projectId) {
      api
        .get<ProjectDetail>(`/projects/${projectId}`)
        .then(setProjectDetail)
        .catch(() => setProjectDetail(null));
    }
  }, [projectId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Audit Reports</h1>
        <p className="mt-1 text-sm text-slate-500">
          Generate and export compliance audit reports in PDF or JSON format.
        </p>
      </div>

      <div className="mx-auto max-w-2xl rounded-xl border border-slate-200 bg-white p-8">
        <div className="flex items-center gap-3">
          <FileBarChart className="h-8 w-8 text-indigo-500" />
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Export Audit Report
            </h2>
            <p className="text-sm text-slate-500">
              Select a project and download the compliance report.
            </p>
          </div>
        </div>

        <div className="mt-6">
          <label className="block text-sm font-medium text-slate-700">
            Project
          </label>
          <select
            value={projectId}
            onChange={(e) => {
              const newId = e.target.value;
              setProjectId(newId);
              setFrameworkId("");
              setProjectDetail(null);
            }}
            className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">Select a project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {projectDetail && projectDetail.frameworks.length > 0 && (
          <div className="mt-4">
            <label className="block text-sm font-medium text-slate-700">
              Framework (optional)
            </label>
            <select
              value={frameworkId}
              onChange={(e) => setFrameworkId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All frameworks</option>
              {projectDetail.frameworks.map((fw) => (
                <option key={fw.id} value={fw.id}>
                  {fw.name} ({fw.control_count} controls)
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="mt-6">
          {projectId ? (
            <ExportButton
              projectId={projectId}
              frameworkId={frameworkId || undefined}
            />
          ) : (
            <p className="text-sm text-slate-400">
              Select a project to enable export.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
