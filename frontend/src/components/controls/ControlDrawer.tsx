"use client";

import { useState, useEffect } from "react";
import { X, ShieldCheck, ShieldAlert, Copy, AlertCircle, FileCode, Clock } from "lucide-react";
import { api } from "@/lib/api";
import type { ControlDetail } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { EvidenceModal } from "@/components/evidence/EvidenceModal";

interface ControlDrawerProps {
  controlId: string | null;
  onClose: () => void;
}

export function ControlDrawer({ controlId, onClose }: ControlDrawerProps) {
  const [control, setControl] = useState<ControlDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  const [isOpen, setIsOpen] = useState(false);
  const [renderId, setRenderId] = useState<string | null>(null);

  useEffect(() => {
    if (controlId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRenderId(controlId);
       
      setIsOpen(true);
       
      setLoading(true);
      api.get<ControlDetail>(`/controls/${controlId}`)
        .then(setControl)
        .finally(() => setLoading(false));
    } else {
      setIsOpen(false);
      const timer = setTimeout(() => {
        setRenderId(null);
        setControl(null);
      }, 300); // Wait for animation
      return () => clearTimeout(timer);
    }
  }, [controlId]);

  // Handle escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!renderId) return null;

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Pass": return "bg-emerald-100 text-emerald-800 border-emerald-200";
      case "Fail": return "bg-red-100 text-red-800 border-red-200";
      case "NeedsReview": return "bg-amber-100 text-amber-800 border-amber-200";
      default: return "bg-slate-100 text-slate-800 border-slate-200";
    }
  };

  const getTimelineIcon = (status: string) => {
    switch (status) {
      case "Pass": return <ShieldCheck className="h-4 w-4 text-emerald-500" />;
      case "Fail": return <ShieldAlert className="h-4 w-4 text-red-500" />;
      case "NeedsReview": return <AlertCircle className="h-4 w-4 text-amber-500" />;
      default: return <Clock className="h-4 w-4 text-slate-500" />;
    }
  };

  return (
    <>
      <div 
        className={`fixed inset-0 z-40 bg-slate-900/40 transition-opacity duration-300 ${isOpen ? "opacity-100" : "opacity-0"}`} 
        onClick={onClose}
        aria-hidden="true"
      />
      <div className={`fixed inset-y-0 right-0 z-50 w-full max-w-md transform overflow-y-auto bg-white shadow-xl transition-transform duration-300 ease-in-out sm:max-w-lg md:max-w-xl ${isOpen ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex h-full flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-slate-900">Control Details</h2>
            <button
              onClick={onClose}
              className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus:outline-none"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="flex-1 p-6">
            {loading ? (
              <div className="flex h-32 items-center justify-center">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
              </div>
            ) : control ? (
              <div className="space-y-8">
                {/* Status Header */}
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium text-indigo-600">{control.control_id_code}</span>
                    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${getStatusColor(control.status)}`}>
                      {control.status}
                    </span>
                  </div>
                  <h3 className="mt-2 text-xl font-bold text-slate-900">{control.title}</h3>
                  <p className="mt-2 text-sm text-slate-600">{control.description}</p>
                </div>

                {/* Remediation Warning */}
                {control.remediation && (
                  <div className="rounded-md bg-amber-50 p-4 border border-amber-200">
                    <div className="flex">
                      <div className="flex-shrink-0">
                        <AlertCircle className="h-5 w-5 text-amber-400" aria-hidden="true" />
                      </div>
                      <div className="ml-3">
                        <h3 className="text-sm font-medium text-amber-800">Remediation Needed</h3>
                        <div className="mt-2 text-sm text-amber-700">
                          <p>{control.remediation}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Citation */}
                <div>
                  <h4 className="text-sm font-medium text-slate-900">Source Citation</h4>
                  <blockquote className="mt-2 border-l-4 border-indigo-200 bg-slate-50 p-3 text-sm italic text-slate-700">
                    {control.source_citation}
                  </blockquote>
                  {control.source_text && (
                    <div className="mt-2 rounded-md bg-slate-50 p-3 text-sm text-slate-600 font-mono text-xs">
                      {control.source_text}
                    </div>
                  )}
                </div>

                {/* Evidence Items */}
                <div>
                  <h4 className="mb-3 text-sm font-medium text-slate-900">Linked Evidence</h4>
                  {control.evidence_items?.length > 0 ? (
                    <ul className="space-y-3">
                      {control.evidence_items.map((evidence) => (
                        <li 
                          key={evidence.id} 
                          className="flex items-center justify-between rounded-lg border border-slate-200 p-3 hover:bg-slate-50 cursor-pointer"
                          onClick={() => setSelectedEvidenceId(evidence.id)}
                        >
                          <div className="flex items-center gap-3">
                            <FileCode className="h-5 w-5 text-slate-400" />
                            <div>
                              {evidence.source_ref.startsWith("http") ? (
                                <a 
                                  href={evidence.source_ref} 
                                  target="_blank" 
                                  rel="noreferrer" 
                                  className="text-sm font-medium text-indigo-600 hover:underline"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {evidence.source_ref}
                                </a>
                              ) : (
                                <p className="text-sm font-medium text-indigo-600">{evidence.source_ref}</p>
                              )}
                              <p className="text-xs text-slate-500">Collected {formatDate(evidence.collected_at)} • {evidence.source_type}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-slate-400" title={evidence.sha256_hash}>
                              {evidence.sha256_hash.substring(0, 8)}...
                            </span>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard.writeText(evidence.sha256_hash);
                              }}
                              className="text-slate-400 hover:text-slate-600"
                              title="Copy hash"
                            >
                              <Copy className="h-4 w-4" />
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-slate-500">No evidence linked.</p>
                  )}
                </div>

                {/* Status Timeline */}
                <div>
                  <h4 className="mb-4 text-sm font-medium text-slate-900">Status Timeline</h4>
                  <div className="flow-root">
                    <ul className="-mb-8">
                      {control.status_history?.map((event, eventIdx) => (
                        <li key={event.id}>
                          <div className="relative pb-8">
                            {eventIdx !== control.status_history.length - 1 ? (
                              <span className="absolute left-4 top-4 -ml-px h-full w-0.5 bg-slate-200" aria-hidden="true" />
                            ) : null}
                            <div className="relative flex space-x-3">
                              <div>
                                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white ring-8 ring-white">
                                  {getTimelineIcon(event.status)}
                                </span>
                              </div>
                              <div className="flex min-w-0 flex-1 justify-between space-x-4 pt-1.5">
                                <div>
                                  <p className="text-sm text-slate-500">
                                    Changed to <span className="font-medium text-slate-900">{event.status}</span>
                                  </p>
                                  {event.rationale && (
                                    <p className="mt-1 text-sm text-slate-600">{event.rationale}</p>
                                  )}
                                </div>
                                <div className="whitespace-nowrap text-right text-sm text-slate-500">
                                  {new Date(event.determined_at).toLocaleDateString()}
                                </div>
                              </div>
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                    {(!control.status_history || control.status_history.length === 0) && (
                      <p className="text-sm text-slate-500">No history available.</p>
                    )}
                  </div>
                </div>

              </div>
            ) : (
              <div className="text-center text-slate-500">Failed to load control details.</div>
            )}
          </div>
        </div>
      </div>
      <EvidenceModal
        evidenceId={selectedEvidenceId}
        onClose={() => setSelectedEvidenceId(null)}
      />
    </>
  );
}
