"""
Role-permission matrix for the SentinellAI platform.
Used by API endpoints via the require_role() dependency.
"""

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "compliance_manager": [
        "projects:read",
        "projects:write",
        "frameworks:read",
        "frameworks:write",
        "controls:read",
        "controls:review",
        "reports:read",
        "reports:export",
        "dashboard:read",
        "connectors:read",
        "connectors:write",
        "connectors:trigger",
        "evidence:read",
    ],
    "devops_engineer": [
        "connectors:read",
        "connectors:write",
        "connectors:trigger",
        "evidence:read",
        "controls:read",
        "dashboard:read",
    ],
    "developer": [
        "controls:read",
        "evidence:read",
        "dashboard:read",
    ],
    "auditor": [
        "controls:read",
        "evidence:read",
        "reports:read",
        "reports:export",
        "dashboard:read",
    ],
}


def has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, [])
    if "*" in perms:
        return True
    return permission in perms
