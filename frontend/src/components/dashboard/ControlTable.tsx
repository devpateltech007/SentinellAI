"use client";

import { Fragment, useState } from "react";
import { cn, statusColor, formatDate } from "@/lib/utils";
import type { Control } from "@/lib/types";
import { ControlDrawer } from "@/components/controls/ControlDrawer";

interface Props {
  controls: Control[];
  projectId?: string;
}

export default function ControlTable({ controls }: Props) {
  const [drawerControlId, setDrawerControlId] = useState<string | null>(null);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr>
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
                onClick={() => setDrawerControlId(control.id)}
              >
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
            </Fragment>
          ))}
        </tbody>
      </table>
      {controls.length === 0 && (
        <div className="py-12 text-center text-sm text-slate-400">
          No controls found. Add a framework to generate controls.
        </div>
      )}
      <ControlDrawer
        controlId={drawerControlId}
        onClose={() => setDrawerControlId(null)}
      />
    </div>
  );
}
