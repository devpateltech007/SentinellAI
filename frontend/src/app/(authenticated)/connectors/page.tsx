"use client";

import { useEffect, useState } from "react";
import {
  Plug,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  Plus,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { Connector, Project } from "@/lib/types";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [formData, setFormData] = useState({
    project_id: "",
    source_type: "github_actions",
    config: '{"owner": "", "repo": ""}',
    schedule: "",
  });
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadConnectors = () => {
    api
      .get<Connector[]>("/connectors")
      .then(setConnectors)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadConnectors();
  }, []);

  const openForm = async () => {
    try {
      const p = await api.get<Project[]>("/projects");
      setProjects(p);
    } catch {
      setProjects([]);
    }
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    setSubmitting(true);

    try {
      const config = JSON.parse(formData.config);
      await api.post("/connectors", {
        project_id: formData.project_id,
        source_type: formData.source_type,
        config,
        schedule: formData.schedule || null,
      });
      setShowForm(false);
      setFormData({
        project_id: "",
        source_type: "github_actions",
        config: '{"owner": "", "repo": ""}',
        schedule: "",
      });
      loadConnectors();
    } catch (err) {
      if (err instanceof SyntaxError) {
        setFormError("Invalid JSON in config field.");
      } else {
        setFormError(
          "Failed to register connector. Make sure you have devops_engineer or admin role.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  const triggerConnector = async (id: string) => {
    await api.post(`/connectors/${id}/trigger`);
    const updated = await api.get<Connector[]>("/connectors");
    setConnectors(updated);
  };

  const statusIcon = (status: string | null) => {
    switch (status) {
      case "success":
        return <CheckCircle className="h-5 w-5 text-emerald-500" />;
      case "error":
        return <XCircle className="h-5 w-5 text-red-500" />;
      default:
        return <Clock className="h-5 w-5 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            Evidence Connectors
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Configure and monitor evidence collection sources.
          </p>
        </div>
        <button
          onClick={openForm}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
        >
          <Plus className="h-4 w-4" />
          Add Connector
        </button>
      </div>

      {showForm && (
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">
              Register New Connector
            </h2>
            <button
              onClick={() => setShowForm(false)}
              className="text-slate-400 hover:text-slate-600"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {formError && (
            <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
              {formError}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Project
              </label>
              <select
                value={formData.project_id}
                onChange={(e) =>
                  setFormData((d) => ({ ...d, project_id: e.target.value }))
                }
                required
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

            <div>
              <label className="block text-sm font-medium text-slate-700">
                Source Type
              </label>
              <select
                value={formData.source_type}
                onChange={(e) =>
                  setFormData((d) => ({ ...d, source_type: e.target.value }))
                }
                className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="github_actions">GitHub Actions</option>
                <option value="iac_config">IaC Config</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700">
                Config (JSON)
              </label>
              <textarea
                value={formData.config}
                onChange={(e) =>
                  setFormData((d) => ({ ...d, config: e.target.value }))
                }
                rows={3}
                className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 font-mono text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700">
                Schedule (optional cron expression)
              </label>
              <input
                type="text"
                value={formData.schedule}
                onChange={(e) =>
                  setFormData((d) => ({ ...d, schedule: e.target.value }))
                }
                placeholder="e.g. 0 */6 * * *"
                className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-lg bg-indigo-600 px-6 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {submitting ? "Registering..." : "Register Connector"}
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        </div>
      ) : connectors.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-4 py-3 font-medium text-slate-600">
                  Source Type
                </th>
                <th className="px-4 py-3 font-medium text-slate-600">
                  Schedule
                </th>
                <th className="px-4 py-3 font-medium text-slate-600">
                  Status
                </th>
                <th className="px-4 py-3 font-medium text-slate-600">
                  Last Run
                </th>
                <th className="px-4 py-3 font-medium text-slate-600">Error</th>
                <th className="px-4 py-3 font-medium text-slate-600">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {connectors.map((connector) => (
                <tr
                  key={connector.id}
                  className="border-b border-slate-100"
                >
                  <td className="px-4 py-3 font-medium text-slate-900">
                    <div className="flex items-center gap-2">
                      <Plug className="h-4 w-4 text-slate-400" />
                      {connector.source_type}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {connector.schedule || "Manual"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {statusIcon(connector.last_status)}
                      <span className="text-sm">
                        {connector.last_status || "Never run"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {connector.last_run_at
                      ? formatDate(connector.last_run_at)
                      : "—"}
                  </td>
                  <td className="max-w-[200px] truncate px-4 py-3 text-xs text-red-500">
                    {connector.last_error || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => triggerConnector(connector.id)}
                      className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Trigger
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border-2 border-dashed border-slate-300 py-16 text-center">
          <Plug className="mx-auto h-12 w-12 text-slate-300" />
          <h3 className="mt-4 text-lg font-medium text-slate-600">
            No connectors configured
          </h3>
          <p className="mt-1 text-sm text-slate-400">
            Click &quot;Add Connector&quot; to register a GitHub Actions or IaC
            connector.
          </p>
        </div>
      )}
    </div>
  );
}
