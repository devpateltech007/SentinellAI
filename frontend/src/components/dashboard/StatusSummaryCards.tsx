"use client";

import { Shield, AlertTriangle, HelpCircle, Clock } from "lucide-react";
import type { DashboardSummary } from "@/lib/types";

interface Props {
  summary: DashboardSummary;
}

export default function StatusSummaryCards({ summary }: Props) {
  const cards = [
    {
      label: "Passed",
      value: summary.pass_count,
      icon: Shield,
      color: "bg-emerald-50 text-emerald-700 border-emerald-200",
      iconColor: "text-emerald-500",
    },
    {
      label: "Failed",
      value: summary.fail_count,
      icon: AlertTriangle,
      color: "bg-red-50 text-red-700 border-red-200",
      iconColor: "text-red-500",
    },
    {
      label: "Needs Review",
      value: summary.needs_review_count,
      icon: HelpCircle,
      color: "bg-amber-50 text-amber-700 border-amber-200",
      iconColor: "text-amber-500",
    },
    {
      label: "Pending",
      value: summary.pending_count,
      icon: Clock,
      color: "bg-slate-50 text-slate-700 border-slate-200",
      iconColor: "text-slate-400",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className={`rounded-xl border p-5 ${card.color}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium opacity-80">{card.label}</p>
                <p className="mt-1 text-3xl font-bold">{card.value}</p>
              </div>
              <Icon className={`h-10 w-10 ${card.iconColor} opacity-60`} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
