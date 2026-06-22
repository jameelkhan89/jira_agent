"""
Jira API client — fetches ticket data from Jira Cloud.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth


@dataclass
class JiraTicket:
    key: str
    summary: str
    description: str
    issue_type: str
    status: str
    priority: str
    reporter: str
    assignee: str
    labels: list[str]
    components: list[str]
    acceptance_criteria_field: Optional[str]  # custom field if exists


class JiraClient:
    def __init__(self) -> None:
        self.base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
        self.email = os.environ["JIRA_EMAIL"]
        self.api_token = os.environ["JIRA_API_TOKEN"]
        self.project_filter = [
            p.strip().upper()
            for p in os.environ.get("JIRA_PROJECT_FILTER", "").split(",")
            if p.strip()
        ]
        self.auth = HTTPBasicAuth(self.email, self.api_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ── Public ─────────────────────────────────────────────────────────────────

    def get_ticket(self, ticket_key: str) -> JiraTicket:
        """Fetch a Jira issue and return a structured JiraTicket."""
        ticket_key = ticket_key.strip().upper()
        self._validate_project(ticket_key)

        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}"
        resp = requests.get(url, auth=self.auth, headers=self.headers, timeout=15)

        if resp.status_code == 401:
            raise PermissionError("Jira authentication failed — check JIRA_EMAIL and JIRA_API_TOKEN.")
        if resp.status_code == 403:
            raise PermissionError(f"Access denied to ticket {ticket_key}.")
        if resp.status_code == 404:
            raise ValueError(f"Ticket '{ticket_key}' not found in Jira.")
        resp.raise_for_status()

        return self._parse_issue(resp.json())

    # ── Private ────────────────────────────────────────────────────────────────

    def _validate_project(self, ticket_key: str) -> None:
        if not self.project_filter:
            return
        project = ticket_key.split("-")[0] if "-" in ticket_key else ""
        if project not in self.project_filter:
            raise ValueError(
                f"Project '{project}' is not in the allowed project filter: "
                f"{', '.join(self.project_filter)}"
            )

    def _parse_issue(self, data: dict) -> JiraTicket:
        fields = data.get("fields", {})

        def safe_get(obj: dict | None, *keys: str, fallback: str = "") -> str:
            for key in keys:
                if obj is None:
                    return fallback
                obj = obj.get(key)  # type: ignore[assignment]
            return str(obj) if obj is not None else fallback

        # Jira Cloud uses Atlassian Document Format (ADF) for descriptions
        description_raw = fields.get("description")
        description = self._adf_to_text(description_raw) if isinstance(description_raw, dict) else (description_raw or "")

        # Try common custom field names for "Acceptance Criteria"
        ac_field = self._find_acceptance_criteria_field(fields)

        return JiraTicket(
            key=data.get("key", ""),
            summary=safe_get(fields, "summary"),
            description=description,
            issue_type=safe_get(fields, "issuetype", "name"),
            status=safe_get(fields, "status", "name"),
            priority=safe_get(fields, "priority", "name"),
            reporter=safe_get(fields, "reporter", "displayName"),
            assignee=safe_get(fields, "assignee", "displayName", fallback="Unassigned"),
            labels=fields.get("labels") or [],
            components=[c.get("name", "") for c in (fields.get("components") or [])],
            acceptance_criteria_field=ac_field,
        )

    def _find_acceptance_criteria_field(self, fields: dict) -> Optional[str]:
        """
        Look for an existing acceptance criteria custom field.
        Common custom field IDs/names vary by Jira instance.
        """
        # Common custom field keys used for AC
        candidate_keys = [
            "customfield_10016",  # common in many instances
            "customfield_10020",
            "customfield_10014",
            "customfield_10034",
        ]
        for key in candidate_keys:
            value = fields.get(key)
            if value:
                if isinstance(value, dict):
                    return self._adf_to_text(value)
                if isinstance(value, str):
                    return value
        return None

    def _adf_to_text(self, adf: dict | None) -> str:
        """Convert Atlassian Document Format JSON to plain text."""
        if not adf:
            return ""
        parts: list[str] = []
        self._walk_adf(adf, parts)
        return "\n".join(parts).strip()

    def _walk_adf(self, node: dict, parts: list[str]) -> None:
        node_type = node.get("type", "")
        content = node.get("content", [])

        if node_type == "text":
            parts.append(node.get("text", ""))
            return

        if node_type in ("paragraph", "heading"):
            inner: list[str] = []
            for child in content:
                self._walk_adf(child, inner)
            parts.append("".join(inner))
            return

        if node_type in ("bulletList", "orderedList"):
            for i, item in enumerate(content, 1):
                inner = []
                for child in item.get("content", []):
                    self._walk_adf(child, inner)
                prefix = f"{i}." if node_type == "orderedList" else "-"
                parts.append(f"{prefix} {''.join(inner)}")
            return

        # Generic fallthrough — recurse into children
        for child in content:
            self._walk_adf(child, parts)
