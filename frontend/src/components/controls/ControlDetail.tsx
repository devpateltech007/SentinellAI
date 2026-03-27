"use client";

import { useState } from "react";
import { cn, statusColor, formatDate } from "@/lib/utils";
import CitationLink from "./CitationLink";
import { api } from "@/lib/api";
import type { ControlDetail as ControlDetailType } from "@/lib/types";

interface Props {
  control: ControlDetailType;
  onUpdated?: (updated: ControlDetailType) => void;
}

export default function ControlDetailView({ control, onUpdated }: Props) {
  const [showReview, setShowReview] = useState(false);
  const [decision, setDecision] = useState<"approve" | "override">("approve");
  const [overrideStatus, setOverrideStatus] = useState("Pass");
  const [justification, setJustification] = useState("");
  const [reviewError, setReviewError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleReview = async () => {
    if (!justification.trim()) {
      setReviewError("Justification is required.");
      return;
    }
    setSubmitting(true);
    setReviewError("");
    try {
      await api.post(`/controls/${control.id}/review`, {
        decision,
        justification,
        override_status: decision === "override" ? overrideStatus : null,
      });
      const updated = await api.get<ControlDetailType>(
        `/controls/${control.id}`,
      );
      onUpdated?.(updated);
      setShowReview(false);
      setJustification("");
    } catch {
      setReviewError(
        "Failed to submit review. You may not have the required role.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-mono text-sm text-slate-500">
            {control.control_id_code}
          </p>
          <h2 className="mt-1 text-2xl font-bold text-slate-900">
            {control.title}
          </h2>
        </div>
        <span
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-semibold",
            statusColor(control.status),
          )}
        >
          {control.status}
        </span>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <h3 className="text-sm font-semibold text-slate-700">Description</h3>
        <p className="mt-2 text-sm text-slate-600">{control.description}</p>

        <h3 className="mt-6 text-sm font-semibold text-slate-700">
          Regulatory Citation
        </h3>
        <CitationLink citation={control.source_citation} />
        {control.source_text && (
          <blockquote className="mt-2 border-l-4 border-indigo-200 pl-4 text-sm italic text-slate-500">
            {control.source_text}
          </blockquote>
        )}
      </div>

      {control.remediation && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h3 className="text-sm font-semibold text-red-800">
            Remediation Guidance
          </h3>
          <p className="mt-2 text-sm text-red-700">{control.remediation}</p>
        </div>
      )}

      {/* Review Section */}
      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700">
            Manual Review
          </h3>
          {!showReview && (
            <button
              onClick={() => setShowReview(true)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Review Control
            </button>
          )}
        </div>

        {showReview && (
          <div className="mt-4 space-y-4">
            {reviewError && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
                {reviewError}
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Decision
              </label>
              <div className="mt-2 flex gap-4">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="decision"
                    value="approve"
                    checked={decision === "approve"}
                    onChange={() => setDecision("approve")}
                    className="text-indigo-600"
                  />
                  <span className="text-sm text-slate-700">
                    Approve current status
                  </span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="decision"
                    value="override"
                    checked={decision === "override"}
                    onChange={() => setDecision("override")}
                    className="text-indigo-600"
                  />
                  <span className="text-sm text-slate-700">
                    Override status
                  </span>
                </label>
              </div>
            </div>

            {decision === "override" && (
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  New Status
                </label>
                <select
                  value={overrideStatus}
                  onChange={(e) => setOverrideStatus(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="Pass">Pass</option>
                  <option value="Fail">Fail</option>
                  <option value="NeedsReview">Needs Review</option>
                  <option value="Pending">Pending</option>
                </select>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-slate-700">
                Justification
              </label>
              <textarea
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                rows={3}
                placeholder="Explain the reasoning for this review decision..."
                className="mt-1 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowReview(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReview}
                disabled={submitting}
                className="rounded-lg bg-indigo-600 px-6 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {submitting ? "Submitting..." : "Submit Review"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <h3 className="text-sm font-semibold text-slate-700">
          Requirements ({control.requirements.length})
        </h3>
        <ul className="mt-3 space-y-3">
          {control.requirements.map((req) => (
            <li key={req.id} className="rounded-md bg-slate-50 p-3">
              <p className="text-sm text-slate-700">{req.description}</p>
              {req.testable_condition && (
                <p className="mt-1 font-mono text-xs text-slate-500">
                  Condition: {req.testable_condition}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <h3 className="text-sm font-semibold text-slate-700">
          Evidence ({control.evidence_items.length})
        </h3>
        {control.evidence_items.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">
            No evidence collected for this control.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {control.evidence_items.map((ev) => (
              <li
                key={ev.id}
                className="flex items-center justify-between rounded-md bg-slate-50 p-3 text-sm"
              >
                <div>
                  <span className="font-medium text-slate-700">
                    {ev.source_type}
                  </span>
                  <span className="ml-2 text-slate-500">{ev.source_ref}</span>
                </div>
                <span className="font-mono text-xs text-slate-400">
                  {formatDate(ev.collected_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <h3 className="text-sm font-semibold text-slate-700">Status History</h3>
        <div className="mt-3 space-y-2">
          {control.status_history.map((entry) => (
            <div
              key={entry.id}
              className="flex items-start gap-3 border-b border-slate-100 pb-2 last:border-0"
            >
              <span
                className={cn(
                  "mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-semibold",
                  statusColor(entry.status),
                )}
              >
                {entry.status}
              </span>
              <div className="flex-1">
                <p className="text-xs text-slate-500">
                  {formatDate(entry.determined_at)}
                </p>
                {entry.rationale && (
                  <p className="mt-1 text-sm text-slate-600">
                    {entry.rationale}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
