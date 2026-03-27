"use client";

import { formatDate } from "@/lib/utils";
import type { EvidenceSummary } from "@/lib/types";

interface Props {
  items: EvidenceSummary[];
}

export default function EvidenceList({ items }: Props) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr>
            <th className="px-4 py-3 font-medium text-slate-600">Source</th>
            <th className="px-4 py-3 font-medium text-slate-600">Reference</th>
            <th className="px-4 py-3 font-medium text-slate-600">
              SHA-256 Hash
            </th>
            <th className="px-4 py-3 font-medium text-slate-600">Collected</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className="border-b border-slate-100 transition-colors hover:bg-slate-50"
            >
              <td className="px-4 py-3">
                <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                  {item.source_type}
                </span>
              </td>
              <td className="max-w-[300px] truncate px-4 py-3 text-slate-700">
                {item.source_ref}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">
                {item.sha256_hash.substring(0, 16)}...
              </td>
              <td className="px-4 py-3 text-xs text-slate-500">
                {formatDate(item.collected_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && (
        <div className="py-12 text-center text-sm text-slate-400">
          No evidence items found.
        </div>
      )}
    </div>
  );
}
