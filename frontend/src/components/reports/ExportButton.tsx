"use client";

import { useState } from "react";
import { Download } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Props {
  projectId: string;
  frameworkId?: string;
}

export default function ExportButton({ projectId, frameworkId }: Props) {
  const [loading, setLoading] = useState(false);

  const handleExport = async (format: "pdf" | "json") => {
    setLoading(true);
    try {
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("sentinellai_token")
          : null;

      const response = await fetch(`${API_BASE}/api/v1/reports/export`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          project_id: projectId,
          framework_id: frameworkId || null,
          format,
        }),
      });

      if (!response.ok) throw new Error("Export failed");

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_report.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Silently handled
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex gap-3">
      <button
        onClick={() => handleExport("json")}
        disabled={loading}
        className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50"
      >
        <Download className="h-4 w-4" />
        Export JSON
      </button>
      <button
        onClick={() => handleExport("pdf")}
        disabled={loading}
        className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-50"
      >
        <Download className="h-4 w-4" />
        Export PDF
      </button>
    </div>
  );
}
