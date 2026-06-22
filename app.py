"""
Flask application — serves the web UI and handles Jira webhooks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Load .env from project root regardless of working directory
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

from src.ac_generator import ACGenerator
from src.jira_client import JiraClient

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _verify_webhook_signature(payload: bytes, signature_header: str | None) -> bool:
    """
    Jira sends an HMAC-SHA256 signature in the X-Hub-Signature header when a
    webhook secret is configured. Format: sha256=<hex_digest>
    """
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        # No secret configured — skip verification (not recommended for prod)
        log.warning("WEBHOOK_SECRET not set; skipping signature verification.")
        return True

    if not signature_header:
        log.warning("Webhook received without signature header.")
        return False

    try:
        algo, provided_digest = signature_header.split("=", 1)
    except ValueError:
        return False

    expected_digest = hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_digest, provided_digest)


def _process_ticket(ticket_key: str) -> dict:
    """Core logic: fetch ticket → generate AC → return result dict."""
    jira = JiraClient()
    generator = ACGenerator()

    ticket = jira.get_ticket(ticket_key)
    result = generator.generate(ticket)

    return {
        "ticket_key": result.ticket_key,
        "ticket_summary": result.ticket_summary,
        "acceptance_criteria": result.acceptance_criteria,
        "model_used": result.model_used,
        "tokens": {
            "input": result.input_tokens,
            "output": result.output_tokens,
        },
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


@app.post("/generate")
def generate():
    """Web UI endpoint — accepts JSON { ticket_key: 'PROJ-123' }."""
    body = request.get_json(silent=True) or {}
    ticket_key = (body.get("ticket_key") or "").strip().upper()

    if not ticket_key:
        return jsonify({"error": "ticket_key is required"}), 400

    log.info("Web UI request: generating AC for %s", ticket_key)

    try:
        result = _process_ticket(ticket_key)
        return jsonify(result)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Unexpected error generating AC for %s", ticket_key)
        return jsonify({"error": f"Internal error: {exc}"}), 500


@app.post("/webhook/jira")
def jira_webhook():
    """
    Jira webhook endpoint.

    Configure in Jira:
      URL:    https://your-host/webhook/jira
      Events: issue_created, issue_updated (filter by JQL if desired)
      Secret: value of WEBHOOK_SECRET env var

    Jira sends a JSON payload. We extract the issue key and generate AC.
    The response is logged; in production you'd write it back to Jira or
    send it to Slack/Teams/etc.
    """
    raw_body = request.get_data()

    # Verify signature
    sig_header = request.headers.get("X-Hub-Signature") or request.headers.get("X-Jira-Signature")
    if not _verify_webhook_signature(raw_body, sig_header):
        log.warning("Webhook signature verification failed.")
        return jsonify({"error": "Invalid signature"}), 401

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Jira webhook payload structure
    webhook_event = payload.get("webhookEvent", "")
    issue = payload.get("issue", {})
    ticket_key = issue.get("key", "")

    log.info("Webhook event '%s' for ticket '%s'", webhook_event, ticket_key)

    if not ticket_key:
        return jsonify({"error": "No issue key found in payload"}), 400

    # Only process issue_created and issue_updated events
    supported_events = {"jira:issue_created", "jira:issue_updated", "issue_created", "issue_updated"}
    if webhook_event not in supported_events:
        log.info("Ignoring event type: %s", webhook_event)
        return jsonify({"status": "ignored", "reason": f"Event '{webhook_event}' not handled"}), 200

    try:
        result = _process_ticket(ticket_key)
        log.info(
            "Generated %d tokens of AC for %s",
            result["tokens"]["output"],
            ticket_key,
        )
        # In a real integration you'd:
        #   - POST the AC back to the Jira ticket as a comment
        #   - Write it to a custom field
        #   - Send it to Slack / Teams
        # For this POC, we return it in the response and log it.
        log.info("AC for %s:\n%s", ticket_key, result["acceptance_criteria"])
        return jsonify({"status": "ok", "result": result}), 200

    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Unexpected error generating AC for %s", ticket_key)
        return jsonify({"error": f"Internal error: {exc}"}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    log.info("Starting Jira AC Agent on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
