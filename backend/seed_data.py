"""Seed script to populate the database with demo data for testing.

Run inside the backend container:
    python -m seed_data
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, async_session
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.framework import Framework, FrameworkName
from app.models.control import Control, ControlStatusEnum
from app.models.requirement import Requirement
from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.models.control_evidence import ControlEvidence
from app.models.control_status import ControlStatus
from app.models.connector import Connector


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


NOW = datetime.now(timezone.utc)


async def seed():
    async with async_session() as db:
        # --- Users ---
        admin = User(
            id=uuid.uuid4(),
            email="admin@sentinellai.dev",
            hashed_password=_hash("admin123"),
            role=UserRole.ADMIN,
        )
        cm = User(
            id=uuid.uuid4(),
            email="cm@sentinellai.dev",
            hashed_password=_hash("cm123456"),
            role=UserRole.COMPLIANCE_MANAGER,
        )
        devops = User(
            id=uuid.uuid4(),
            email="devops@sentinellai.dev",
            hashed_password=_hash("devops123"),
            role=UserRole.DEVOPS_ENGINEER,
        )
        auditor = User(
            id=uuid.uuid4(),
            email="auditor@sentinellai.dev",
            hashed_password=_hash("auditor123"),
            role=UserRole.AUDITOR,
        )
        for u in [admin, cm, devops, auditor]:
            db.add(u)

        # --- Project ---
        project = Project(id=uuid.uuid4(), name="Healthcare App Compliance")
        db.add(project)

        # --- Framework ---
        framework = Framework(
            id=uuid.uuid4(),
            project_id=project.id,
            name=FrameworkName.HIPAA,
            version="1.0",
        )
        db.add(framework)

        # --- Controls (variety of statuses) ---
        controls_data = [
            {
                "code": "HIPAA-AC-001",
                "title": "Access Control Implementation",
                "desc": "Implement technical policies and procedures for electronic information systems that maintain ePHI to allow access only to authorized persons or software programs.",
                "citation": "§ 164.312(a)(1)",
                "status": ControlStatusEnum.PASS,
            },
            {
                "code": "HIPAA-AC-002",
                "title": "Unique User Identification",
                "desc": "Assign a unique name and/or number for identifying and tracking user identity.",
                "citation": "§ 164.312(a)(2)(i)",
                "status": ControlStatusEnum.PASS,
            },
            {
                "code": "HIPAA-AU-001",
                "title": "Audit Controls",
                "desc": "Implement hardware, software, and/or procedural mechanisms that record and examine activity in information systems that contain or use ePHI.",
                "citation": "§ 164.312(b)",
                "status": ControlStatusEnum.FAIL,
            },
            {
                "code": "HIPAA-IA-001",
                "title": "Integrity Controls",
                "desc": "Implement policies and procedures to protect ePHI from improper alteration or destruction.",
                "citation": "§ 164.312(c)(1)",
                "status": ControlStatusEnum.NEEDS_REVIEW,
            },
            {
                "code": "HIPAA-SC-001",
                "title": "Transmission Security",
                "desc": "Implement technical security measures to guard against unauthorized access to ePHI being transmitted over an electronic communications network.",
                "citation": "§ 164.312(e)(1)",
                "status": ControlStatusEnum.PASS,
            },
            {
                "code": "HIPAA-SC-002",
                "title": "Encryption at Rest",
                "desc": "Implement a mechanism to encrypt ePHI whenever deemed appropriate.",
                "citation": "§ 164.312(a)(2)(iv)",
                "status": ControlStatusEnum.PENDING,
            },
            {
                "code": "HIPAA-CM-001",
                "title": "Configuration Management",
                "desc": "Establish and maintain baseline configurations and inventories of organizational information systems.",
                "citation": "§ 164.310(d)(1)",
                "status": ControlStatusEnum.FAIL,
            },
            {
                "code": "HIPAA-IR-001",
                "title": "Incident Response Procedures",
                "desc": "Implement policies and procedures to address security incidents.",
                "citation": "§ 164.308(a)(6)(i)",
                "status": ControlStatusEnum.NEEDS_REVIEW,
            },
        ]

        controls = []
        for cd in controls_data:
            c = Control(
                id=uuid.uuid4(),
                framework_id=framework.id,
                control_id_code=cd["code"],
                title=cd["title"],
                description=cd["desc"],
                source_citation=cd["citation"],
                source_text=f"Regulatory text for {cd['citation']}",
                status=cd["status"],
                generated_at=NOW - timedelta(days=3),
            )
            db.add(c)
            controls.append(c)

        # --- Requirements ---
        for ctrl in controls:
            for i in range(2):
                req = Requirement(
                    id=uuid.uuid4(),
                    control_id=ctrl.id,
                    description=f"Requirement {i+1} for {ctrl.control_id_code}: Verify that the control objective is met.",
                    testable_condition=f"{ctrl.control_id_code}_REQ_{i+1} == true",
                    citation=ctrl.source_citation,
                )
                db.add(req)

        # --- Evidence Items ---
        evidence_items = []
        evidence_data = [
            {
                "source_type": EvidenceSourceType.GITHUB_ACTIONS,
                "source_ref": "https://github.com/acme/app/actions/runs/12345",
                "content": {
                    "run_id": 12345,
                    "name": "CI Pipeline",
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "main",
                    "logging_enabled": True,
                    "access_control": True,
                },
            },
            {
                "source_type": EvidenceSourceType.GITHUB_ACTIONS,
                "source_ref": "https://github.com/acme/app/actions/runs/12346",
                "content": {
                    "run_id": 12346,
                    "name": "Security Scan",
                    "status": "completed",
                    "conclusion": "failure",
                    "head_branch": "main",
                    "encryption_at_rest": False,
                },
            },
            {
                "source_type": EvidenceSourceType.IAC_CONFIG,
                "source_ref": "/infra/terraform/main.tf",
                "content": {
                    "resource_type": "aws_s3_bucket",
                    "encryption": "AES256",
                    "logging": True,
                    "access_control": "private",
                    "versioning": True,
                },
            },
            {
                "source_type": EvidenceSourceType.IAC_CONFIG,
                "source_ref": "/infra/k8s/deployment.yaml",
                "content": {
                    "kind": "Deployment",
                    "namespace": "production",
                    "replicas": 3,
                    "security_context": {"run_as_non_root": True},
                    "resource_limits": True,
                },
            },
        ]

        for ed in evidence_data:
            import hashlib, json
            content_str = json.dumps(ed["content"], sort_keys=True)
            ev = EvidenceItem(
                id=uuid.uuid4(),
                source_type=ed["source_type"],
                source_ref=ed["source_ref"],
                collected_at=NOW - timedelta(hours=6),
                sha256_hash=hashlib.sha256(content_str.encode()).hexdigest(),
                content_json=ed["content"],
            )
            db.add(ev)
            evidence_items.append(ev)

        await db.flush()

        # --- Link evidence to controls ---
        for i, ctrl in enumerate(controls):
            ev = evidence_items[i % len(evidence_items)]
            db.add(ControlEvidence(control_id=ctrl.id, evidence_id=ev.id))

        # --- Status history ---
        for ctrl in controls:
            db.add(
                ControlStatus(
                    id=uuid.uuid4(),
                    control_id=ctrl.id,
                    status=ctrl.status,
                    determined_at=NOW - timedelta(hours=2),
                    rationale=f"Automated evaluation: {ctrl.status.value} based on linked evidence analysis.",
                )
            )
            if ctrl.status == ControlStatusEnum.FAIL:
                db.add(
                    ControlStatus(
                        id=uuid.uuid4(),
                        control_id=ctrl.id,
                        status=ControlStatusEnum.PASS,
                        determined_at=NOW - timedelta(days=7),
                        rationale="Previous evaluation: control was passing.",
                    )
                )

        # --- Connector ---
        connector = Connector(
            id=uuid.uuid4(),
            project_id=project.id,
            source_type="github_actions",
            config_json={"owner": "acme", "repo": "app"},
            schedule="0 */6 * * *",
            last_status="success",
            last_run_at=NOW - timedelta(hours=6),
            created_by=devops.id,
        )
        db.add(connector)

        await db.commit()
        print("Seed data inserted successfully!")
        print(f"  Admin login: admin@sentinellai.dev / admin123")
        print(f"  CM login:    cm@sentinellai.dev / cm123456")
        print(f"  DevOps login: devops@sentinellai.dev / devops123")
        print(f"  Auditor login: auditor@sentinellai.dev / auditor123")
        print(f"  Project: {project.name} (id={project.id})")
        print(f"  Controls: {len(controls)}")
        print(f"  Evidence: {len(evidence_items)}")


if __name__ == "__main__":
    asyncio.run(seed())
