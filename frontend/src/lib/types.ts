export type UserRole = "admin" | "compliance_manager" | "devops_engineer" | "developer" | "auditor";

export type ControlStatus = "Pass" | "Fail" | "NeedsReview" | "Pending";

export type EvidenceSourceType = "github_actions" | "iac_config" | "app_log";

export type ReportFormat = "pdf" | "json";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  org_id: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Project {
  id: string;
  name: string;
  org_id: string | null;
  created_at: string;
  framework_count: number;
}

export interface ProjectDetail extends Project {
  frameworks: FrameworkSummary[];
}

export interface FrameworkSummary {
  id: string;
  name: string;
  version: string;
  control_count: number;
  pass_count: number;
  fail_count: number;
  needs_review_count: number;
}

export interface Framework {
  id: string;
  project_id: string;
  name: string;
  version: string;
  doc_hash: string | null;
  ingested_at: string | null;
  created_at: string;
  control_count: number;
  status_summary: Record<string, number>;
}

export interface Control {
  id: string;
  framework_id: string;
  control_id_code: string;
  title: string;
  description: string;
  source_citation: string;
  status: ControlStatus;
  generated_at: string;
}

export interface ControlDetail extends Control {
  source_text: string | null;
  reviewed_by: string | null;
  requirements: Requirement[];
  evidence_items: EvidenceSummary[];
  status_history: StatusHistoryEntry[];
  remediation: string | null;
}

export interface Requirement {
  id: string;
  description: string;
  testable_condition: string | null;
  citation: string | null;
}

export interface EvidenceSummary {
  id: string;
  source_type: EvidenceSourceType;
  source_ref: string;
  collected_at: string;
  sha256_hash: string;
}

export interface EvidenceDetail extends EvidenceSummary {
  content_json: Record<string, unknown>;
  redacted: boolean;
  linked_control_ids: string[];
}

export interface EvidenceListResponse {
  items: EvidenceSummary[];
  total: number;
  page: number;
  size: number;
}

export interface StatusHistoryEntry {
  id: string;
  status: ControlStatus;
  determined_at: string;
  evidence_ids: string[] | null;
  rationale: string | null;
}

export interface Connector {
  id: string;
  project_id: string;
  source_type: string;
  schedule: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
}

export interface DashboardSummary {
  pass_count: number;
  fail_count: number;
  needs_review_count: number;
  pending_count: number;
  total_controls: number;
  evidence_coverage: number;
  recent_failures: FailureSummary[];
}

export interface FailureSummary {
  control_id: string;
  control_id_code: string;
  title: string;
  failed_at: string;
  reason: string | null;
}
