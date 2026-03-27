"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { cn, statusColor, formatDate } from "@/lib/utils";
import type { Control } from "@/lib/types";

interface Props {
  controls: Control[];
  projectId?: string;
}

export default function ControlTable({ controls, projectId }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr>
            <th className="w-8 px-4 py-3" />
            <th className="px-4 py-3 font-medium text-slate-600">Control ID</th>
            <th className="px-4 py-3 font-medium text-slate-600">Title</th>
            <th className="px-4 py-3 font-medium text-slate-600">Status</th>
            <th className="px-4 py-3 font-medium text-slate-600">Citation</th>
            <th className="px-4 py-3 font-medium text-slate-600">Generated</th>
          </tr>
        </thead>
        <tbody>
          {controls.map((control) => (
            <Fragment key={control.id}>
              <tr
                className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-slate-50"
                onClick={() =>
                  setExpandedId(expandedId === control.id ? null : control.id)
                }
              >
                <td className="px-4 py-3">
                  {expandedId === control.id ? (
                    <ChevronDown className="h-4 w-4 text-slate-400" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-slate-400" />
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs font-medium">
                  {control.control_id_code}
                </td>
                <td className="px-4 py-3 font-medium text-slate-900">
                  {control.title}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold",
                      statusColor(control.status),
                    )}
                  >
                    {control.status}
                  </span>
                </td>
                <td className="max-w-[200px] truncate px-4 py-3 text-xs text-slate-500">
                  {control.source_citation}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {formatDate(control.generated_at)}
                </td>
              </tr>
              {expandedId === control.id && (
                <tr key={`${control.id}-expanded`}>
                  <td colSpan={6} className="bg-slate-50 px-8 py-4">
                    <p className="text-sm text-slate-700">
                      {control.description}
                    </p>
                    <div className="mt-3">
                      <Link
                        href={
                          projectId
                            ? `/projects/${projectId}/controls/${control.id}`
                            : `/controls/${control.id}`
                        }
                        className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        View Details <ExternalLink className="h-3.5 w-3.5" />
                      </Link>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {controls.length === 0 && (
        <div className="py-12 text-center text-sm text-slate-400">
          No controls found. Add a framework to generate controls.
        </div>
      )}
    </div>
  );
}
