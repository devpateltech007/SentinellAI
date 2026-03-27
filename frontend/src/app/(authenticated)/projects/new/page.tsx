"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [frameworks, setFrameworks] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const toggleFramework = (fw: string) => {
    setFrameworks((prev) =>
      prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw],
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (frameworks.length === 0) {
      setError("Select at least one framework");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const project = await api.post<{ id: string }>("/projects", {
        name,
        frameworks,
      });

      for (const fw of frameworks) {
        await api.post(`/projects/${project.id}/frameworks`, { name: fw });
      }

      router.push(`/projects/${project.id}`);
    } catch {
      setError("Failed to create project. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-bold text-slate-900">
        Create Compliance Project
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Select frameworks to generate compliance controls.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Project Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="e.g., Healthcare App Compliance"
            className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Regulatory Frameworks
          </label>
          <p className="mt-1 text-xs text-slate-400">
            Select one or more frameworks for control generation.
          </p>

          <div className="mt-3 grid grid-cols-2 gap-4">
            {["HIPAA", "GDPR"].map((fw) => (
              <button
                key={fw}
                type="button"
                onClick={() => toggleFramework(fw)}
                className={`rounded-xl border-2 p-6 text-left transition-all ${
                  frameworks.includes(fw)
                    ? "border-indigo-600 bg-indigo-50"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <h3 className="text-lg font-semibold text-slate-900">{fw}</h3>
                <p className="mt-1 text-xs text-slate-500">
                  {fw === "HIPAA"
                    ? "Health Insurance Portability and Accountability Act"
                    : "General Data Protection Regulation"}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={() => router.back()}
            className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Creating..." : "Create Project"}
          </button>
        </div>
      </form>
    </div>
  );
}
