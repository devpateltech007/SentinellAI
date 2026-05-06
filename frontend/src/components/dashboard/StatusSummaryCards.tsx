"use client";

import { useRef, useEffect, useState } from "react";
import { Shield, AlertTriangle, HelpCircle, Clock } from "lucide-react";
import type { DashboardSummary } from "@/lib/types";

interface Props {
  summary: DashboardSummary;
}

export default function StatusSummaryCards({ summary }: Props) {
  const prevSummaryRef = useRef<DashboardSummary | null>(null);
  const [changedKeys, setChangedKeys] = useState<Set<keyof DashboardSummary>>(new Set());

  useEffect(() => {
    if (prevSummaryRef.current) {
      const changes = new Set<keyof DashboardSummary>();
      if (prevSummaryRef.current.pass_count !== summary.pass_count) changes.add("pass_count");
      if (prevSummaryRef.current.fail_count !== summary.fail_count) changes.add("fail_count");
      if (prevSummaryRef.current.needs_review_count !== summary.needs_review_count) changes.add("needs_review_count");
      if (prevSummaryRef.current.pending_count !== summary.pending_count) changes.add("pending_count");
      
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setChangedKeys(changes);
      
      prevSummaryRef.current = summary;

      // Clear the animation state after 1 second
      if (changes.size > 0) {
         
        const timer = setTimeout(() => setChangedKeys(new Set()), 1000);
        return () => clearTimeout(timer);
      }
    } else {
      prevSummaryRef.current = summary;
    }
  }, [summary]);

  const cards = [
    {
      label: "Passed",
      value: summary.pass_count,
      dataKey: "pass_count" as keyof DashboardSummary,
      icon: Shield,
      color: "bg-emerald-50 text-emerald-700 border-emerald-200",
      iconColor: "text-emerald-500",
    },
    {
      label: "Failed",
      value: summary.fail_count,
      dataKey: "fail_count" as keyof DashboardSummary,
      icon: AlertTriangle,
      color: "bg-red-50 text-red-700 border-red-200",
      iconColor: "text-red-500",
    },
    {
      label: "Needs Review",
      value: summary.needs_review_count,
      dataKey: "needs_review_count" as keyof DashboardSummary,
      icon: HelpCircle,
      color: "bg-amber-50 text-amber-700 border-amber-200",
      iconColor: "text-amber-500",
    },
    {
      label: "Pending",
      value: summary.pending_count,
      dataKey: "pending_count" as keyof DashboardSummary,
      icon: Clock,
      color: "bg-slate-50 text-slate-700 border-slate-200",
      iconColor: "text-slate-400",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        const isChanged = changedKeys.has(card.dataKey);
        return (
          <div
            key={card.label}
            className={`rounded-xl border p-5 transition-all duration-500 ${card.color} ${isChanged ? "scale-105 shadow-lg" : ""}`}
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
