"use client";

import { useState, useEffect } from "react";
import { X, Copy, ShieldCheck, ShieldAlert, ShieldQuestion, Loader2, FileCode } from "lucide-react";
import { api } from "@/lib/api";
import type { EvidenceDetail } from "@/lib/types";
import { formatDate } from "@/lib/utils";

interface EvidenceModalProps {
  evidenceId: string | null;
  onClose: () => void;
}

export function EvidenceModal({ evidenceId, onClose }: EvidenceModalProps) {
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [integrityStatus, setIntegrityStatus] = useState<"loading" | "valid" | "invalid" | "error">("loading");

  useEffect(() => {
    if (!evidenceId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEvidence(null);
       
      setIntegrityStatus("loading");
      return;
    }

     
    setLoading(true);
    api.get<EvidenceDetail>(`/evidence/${evidenceId}`)
      .then(setEvidence)
      .finally(() => setLoading(false));

    // Also check integrity
    setIntegrityStatus("loading");
    api.get<{ integrity_valid: boolean }>(`/evidence/${evidenceId}/verify`)
      .then((res) => setIntegrityStatus(res.integrity_valid ? "valid" : "invalid"))
      .catch(() => setIntegrityStatus("error"));

  }, [evidenceId]);

  // Handle escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!evidenceId) return null;

  const integrityConfigs = {
    loading: { icon: Loader2, text: "Verifying...", className: "text-slate-400" },
    valid:   { icon: ShieldCheck, text: "Integrity Verified", className: "text-emerald-600" },
    invalid: { icon: ShieldAlert, text: "TAMPERED", className: "text-red-600 font-bold" },
    error:   { icon: ShieldQuestion, text: "Check unavailable", className: "text-slate-400" },
  };

  const ConfigIcon = integrityConfigs[integrityStatus].icon;

  return (
    <>
      <div 
        className="fixed inset-0 z-[60] bg-slate-900/40 backdrop-blur-sm transition-opacity" 
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="fixed inset-0 z-[70] overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4 text-center sm:p-0">
          <div className="relative transform overflow-hidden rounded-xl bg-white text-left shadow-2xl transition-all sm:my-8 sm:w-full sm:max-w-3xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                <FileCode className="h-5 w-5 text-indigo-600" />
                Evidence Details
              </h3>
              <button
                onClick={onClose}
                className="rounded-md bg-white text-slate-400 hover:text-slate-500 focus:outline-none"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <div className="px-6 py-5">
              {loading ? (
                <div className="flex h-48 items-center justify-center">
                  <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
                </div>
              ) : evidence ? (
                <div className="space-y-6">
                  {/* Metadata Header */}
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{evidence.source_ref}</p>
                      <p className="text-sm text-slate-500">Collected {formatDate(evidence.collected_at)}</p>
                      <span className="mt-2 inline-flex items-center rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                        {evidence.source_type}
                      </span>
                    </div>

                    <div className="flex flex-col items-end gap-2">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-slate-50 border ${integrityConfigs[integrityStatus].className.includes("emerald") ? "border-emerald-200" : integrityConfigs[integrityStatus].className.includes("red") ? "border-red-200" : "border-slate-200"} ${integrityConfigs[integrityStatus].className}`}>
                        <ConfigIcon className={`h-3.5 w-3.5 ${integrityStatus === 'loading' ? 'animate-spin' : ''}`} />
                        {integrityConfigs[integrityStatus].text}
                      </span>
                      
                      {evidence.redacted && (
                        <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                          Redacted
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Hash Bar */}
                  <div className="flex items-center justify-between rounded-lg bg-slate-50 p-3 border border-slate-200">
                    <div className="flex flex-col">
                      <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">SHA-256 Checksum</span>
                      <span className="font-mono text-sm text-slate-700">{evidence.sha256_hash}</span>
                    </div>
                    <button
                      onClick={() => navigator.clipboard.writeText(evidence.sha256_hash)}
                      className="ml-4 rounded p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                      title="Copy full hash"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                  </div>

                  {/* JSON Content */}
                  <div>
                    <h4 className="mb-2 text-sm font-medium text-slate-900">Raw Content</h4>
                    <div className="relative rounded-lg bg-slate-900 p-4">
                      <pre className="max-h-96 overflow-auto text-sm text-emerald-400 font-mono">
                        {JSON.stringify(evidence.content_json, null, 2)}
                      </pre>
                      <button
                        onClick={() => navigator.clipboard.writeText(JSON.stringify(evidence.content_json, null, 2))}
                        className="absolute top-2 right-2 rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
                        title="Copy JSON"
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center text-slate-500">Failed to load evidence details.</div>
              )}
            </div>
            
            <div className="bg-slate-50 px-6 py-4 flex justify-end">
              <button
                type="button"
                className="inline-flex justify-center rounded-md border border-slate-300 bg-white px-4 py-2 text-base font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none sm:text-sm"
                onClick={onClose}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
