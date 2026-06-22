"""
Acceptance Criteria generator — uses Claude to produce structured AC
from a Jira ticket.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic

from .jira_client import JiraTicket


@dataclass
class ACResult:
    ticket_key: str
    ticket_summary: str
    acceptance_criteria: str
    model_used: str
    input_tokens: int
    output_tokens: int


_SYSTEM_PROMPT = """You are a senior product manager and QA engineer helping to write high-quality
acceptance criteria for software tickets. Your acceptance criteria must be:

- Written in Gherkin-style "Given / When / Then" format where it makes sense, or as a clear
  numbered checklist for simpler requirements
- Specific, testable, and unambiguous
- Covering happy paths, edge cases, and relevant error states
- Realistic given the information provided — don't invent business rules not implied by the ticket
- Concise but complete — aim for 5–12 criteria per ticket, more if the ticket is complex

Format your response as clean Markdown. Start with a brief one-sentence framing line, then
provide the acceptance criteria. Do not add padding, disclaimers, or sign-offs."""


def _build_user_prompt(ticket: JiraTicket) -> str:
    parts = [
        f"**Ticket:** {ticket.key}",
        f"**Type:** {ticket.issue_type}",
        f"**Priority:** {ticket.priority}",
        f"**Summary:** {ticket.summary}",
    ]

    if ticket.components:
        parts.append(f"**Components:** {', '.join(ticket.components)}")

    if ticket.labels:
        parts.append(f"**Labels:** {', '.join(ticket.labels)}")

    if ticket.description:
        parts.append(f"\n**Description:**\n{ticket.description}")

    if ticket.acceptance_criteria_field:
        parts.append(
            f"\n**Existing Acceptance Criteria (partial — expand and improve):**\n"
            f"{ticket.acceptance_criteria_field}"
        )

    parts.append(
        "\nBased on the above, generate comprehensive acceptance criteria for this ticket."
    )

    return "\n".join(parts)


class ACGenerator:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def generate(self, ticket: JiraTicket) -> ACResult:
        """Generate acceptance criteria for a Jira ticket."""
        user_prompt = _build_user_prompt(ticket)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        ac_text = "".join(
            block.text for block in message.content if hasattr(block, "text")
        )

        return ACResult(
            ticket_key=ticket.key,
            ticket_summary=ticket.summary,
            acceptance_criteria=ac_text,
            model_used=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
