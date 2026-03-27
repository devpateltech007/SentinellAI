"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { ControlDetail } from "@/lib/types";
import ControlDetailView from "@/components/controls/ControlDetail";

export default function ControlDetailPage() {
  const params = useParams();
  const controlId = params.cid as string;
  const projectId = params.id as string;
  const [control, setControl] = useState<ControlDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<ControlDetail>(`/controls/${controlId}`)
      .then(setControl)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [controlId]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  if (!control) {
    return <div className="text-center text-slate-500">Control not found.</div>;
  }

  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${projectId}`}
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to project
      </Link>
      <ControlDetailView control={control} onUpdated={setControl} />
    </div>
  );
}
