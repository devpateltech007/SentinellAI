# SentinellAI
An AI-Powered Platform for Automated Compliance Auditing
# 🧠 AI-Powered Platform for Automated Compliance Auditing

## 📌 Project Overview

Modern software systems must comply with continuously evolving regulations such as **HIPAA (Healthcare)** and **GDPR (Data Privacy)**. Compliance today is largely manual, fragmented, and expensive — requiring interpretation of legal documents, mapping them to technical controls, and collecting audit evidence across multiple systems.

This project proposes an **AI-powered compliance platform** that bridges the gap between regulatory intent and verifiable software-level technical evidence.

Our system introduces a centralized **"Compliance Brain"** powered by Retrieval-Augmented Generation (RAG) to:

* Interpret regulatory requirements
* Convert them into structured technical controls
* Map controls to actionable software checks
* Automate evidence collection
* Provide continuous compliance readiness
* Detect logic-level and authorization failures
* Generate actionable remediation guidance

---

## 👥 Team Members

* **Dev Patel**
* **Harishita Gupta**
* **Indraneel Sarode**
* **Vatsal Gandhi**

---

## 🎯 Problem Statement

Maintaining regulatory compliance involves:

1. Understanding applicable laws (HIPAA, GDPR, etc.)
2. Translating legal text into technical requirements
3. Verifying that systems meet those requirements
4. Collecting and maintaining audit evidence

Current compliance methods are:

* Manual and document-heavy
* Slow and expensive
* Prone to human error
* Limited in detecting business-logic failures

This leads to the **"Black Box Problem"** — where subtle authorization or access control issues remain undetected by traditional checklist-based compliance tools.

---

## 🚀 Proposed Solution

Our platform introduces an AI-driven approach to compliance automation through:

### 1️⃣ Compliance Brain (Core Engine)

* Uses **RAG (Retrieval-Augmented Generation)**
* Parses regulatory documents
* Converts regulations into structured, machine-readable controls
* Maps legal intent to software-level requirements

Example:

> HIPAA Requirement: "Minimum necessary access must be enforced."

Converted Into:

* Role-Based Access Control (RBAC) implemented?
* Admin privileges restricted?
* Access logs enabled?
* Unauthorized endpoint exposure present?

---

### 2️⃣ Structured Control Framework

Controls are stored in a structured format (JSON schema), such as:

```json
{
  "control_id": "HIPAA-AC-001",
  "description": "Minimum Necessary Access",
  "technical_checks": [
    "RBAC implemented",
    "Admin roles limited",
    "Audit logs enabled"
  ]
}
```

---

### 3️⃣ Automated Evidence Collection

The platform integrates with:

* GitHub (codebase scanning)
* CI/CD pipelines
* Cloud configuration APIs
* Application logs

Evidence is automatically collected and mapped to compliance controls.

---

### 4️⃣ Authorization & Black-Box Testing

Optional runtime verification includes:

* Endpoint access testing
* Role-permission mismatch detection
* Minimum necessary access validation
* Detection of business logic vulnerabilities

---

### 5️⃣ Continuous Monitoring Dashboard

* Real-time compliance status
* Control-level pass/fail indicators
* Evidence logs
* AI-generated remediation suggestions

---

## 🏗️ System Architecture (High-Level)

```
Regulatory Documents
        ↓
   RAG Engine
        ↓
Structured Control Model (JSON)
        ↓
Evidence Orchestrator
        ↓
- GitHub Scanner
- Cloud Config Scanner
- Log Analyzer
- Black-Box Tester
        ↓
Compliance Scoring Engine
        ↓
Dashboard & Remediation Layer
```

---

## 🧩 Current Project Scope (Phase 1)

We are initially focusing on:

* HIPAA Security Rule
* Access Control Requirements
* Role-Based Access Control validation
* Authorization logic verification
* Automated GitHub code analysis (read-only)

---

## 🛠️ Tech Stack (Current & Planned)

### Backend

* Python (FastAPI)
* LLM Integration (RAG pipeline)
* Vector Database (for regulation retrieval)

### Integrations

* GitHub API
* Cloud Config APIs (AWS/GCP/Azure – planned)

### AI Components

* Retrieval-Augmented Generation
* Structured control extraction
* Remediation suggestion engine

### Security Testing

* OWASP Top 10 reference checks
* Authorization testing framework

---

## 📚 Key Concepts & Research Areas

* HIPAA Security Rule
* GDPR basics
* ISO 27001 (Security Management)
* ISO 42001 (AI Governance)
* OWASP Top 10
* Policy-as-Code (OPA)
* Role-Based Access Control (RBAC)

---

## 📈 Long-Term Vision

* Multi-framework support (HIPAA, GDPR, SOC 2)
* AI governance compliance checks
* Continuous AI model monitoring
* Vendor risk evaluation modules
* Enterprise audit export reports

---

## 🧪 Research Contribution

This project contributes by:

* Bridging legal language to software-level validation
* Introducing explainable AI for compliance reasoning
* Detecting logic-level failures beyond static checklist tools
* Enabling developer-friendly compliance automation

---

## 📅 Current Status

* Project Abstract Finalized
* Research Phase Ongoing
* Initial Architecture Designed
* RAG Pipeline Prototype In Progress
* Control Schema Draft Created

---

## ⚠️ Disclaimer

This platform is intended for research and automation assistance purposes. It does not replace legal counsel or certified compliance audits.

---

## 📬 Contact

For questions or collaboration opportunities, please reach out to the team members listed above.

---

⭐ If you find this project interesting, consider giving the repository a star!
