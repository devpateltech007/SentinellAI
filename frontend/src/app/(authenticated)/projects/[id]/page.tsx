"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ProjectDetail, Control } from "@/lib/types";
import ControlTable from "@/components/dashboard/ControlTable";
import { cn } from "@/lib/utils";

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [controls, setControls] = useState<Control[]>([]);
  const [activeFramework, setActiveFramework] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<ProjectDetail>(`/projects/${projectId}`)
      .then((data) => {
        setProject(data);
        if (data.frameworks.length > 0) {
          setActiveFramework(data.frameworks[0].id);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    if (activeFramework) {
      api
        .get<Control[]>(
          `/projects/${projectId}/frameworks/${activeFramework}/controls`,
        )
        .then(setControls)
        .catch(() => {});
    }
  }, [projectId, activeFramework]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  if (!project) {
    return <div className="text-center text-slate-500">Project not found.</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{project.name}</h1>
        <p className="mt-1 text-sm text-slate-500">
          {project.frameworks.length} framework(s)
        </p>
      </div>

      {project.frameworks.length === 0 && (
        <div className="rounded-xl border-2 border-dashed border-slate-300 py-12 text-center">
          <p className="text-sm text-slate-500">
            No frameworks added yet. Add a framework when creating a new project to generate controls.
          </p>
        </div>
      )}

      {project.frameworks.length > 0 && (
        <div className="flex gap-2 border-b border-slate-200">
          {project.frameworks.map((fw) => (
            <button
              key={fw.id}
              onClick={() => setActiveFramework(fw.id)}
              className={cn(
                "border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
                activeFramework === fw.id
                  ? "border-indigo-600 text-indigo-700"
                  : "border-transparent text-slate-500 hover:text-slate-700",
              )}
            >
              {fw.name}
              <span className="ml-2 text-xs text-slate-400">
                ({fw.control_count} controls)
              </span>
            </button>
          ))}
        </div>
      )}

      {activeFramework && (
        <>
          {project.frameworks
            .filter((fw) => fw.id === activeFramework)
            .map((fw) => (
              <div key={fw.id} className="flex gap-4">
                <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm">
                  <span className="font-semibold text-emerald-700">
                    {fw.pass_count}
                  </span>{" "}
                  <span className="text-emerald-600">Pass</span>
                </div>
                <div className="rounded-lg bg-red-50 px-4 py-2 text-sm">
                  <span className="font-semibold text-red-700">
                    {fw.fail_count}
                  </span>{" "}
                  <span className="text-red-600">Fail</span>
                </div>
                <div className="rounded-lg bg-amber-50 px-4 py-2 text-sm">
                  <span className="font-semibold text-amber-700">
                    {fw.needs_review_count}
                  </span>{" "}
                  <span className="text-amber-600">Needs Review</span>
                </div>
              </div>
            ))}

          <ControlTable controls={controls} projectId={projectId} />
        </>
      )}
    </div>
  );
}
