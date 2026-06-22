# Jira AC Agent

An AI-powered agent that reads Jira tickets and generates structured acceptance criteria using Claude. Includes a web UI and a Jira webhook integration.

---

## Features

- **Web UI** — enter any ticket key and get acceptance criteria instantly
- **Jira webhook** — automatically triggered when a Jira issue is created or updated
- **Configurable via `.env`** — all credentials and settings in one place
- **HMAC webhook verification** — validates Jira's signature before processing
- **Gherkin + checklist output** — uses Given/When/Then where appropriate, falls back to numbered lists for simpler requirements

---

## Project structure

```
jira-ac-agent/
├── app.py                  # Flask app (web UI + webhook endpoint)
├── src/
│   ├── jira_client.py      # Jira REST API client
│   └── ac_generator.py     # Claude-powered AC generator
├── templates/
│   └── index.html          # Web UI
├── requirements.txt
├── .env.example            # Copy to .env and fill in
└── README.md
```

---

## Setup

### 1. Clone / copy the project

```bash
cd jira-ac-agent
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values:

| Variable | Description |
|---|---|
| `JIRA_BASE_URL` | Your Jira Cloud URL, e.g. `https://yourco.atlassian.net` |
| `JIRA_EMAIL` | The email of the Jira account that owns the API token |
| `JIRA_API_TOKEN` | Jira API token (generate at id.atlassian.com) |
| `JIRA_PROJECT_FILTER` | Comma-separated project keys to allow (blank = all) |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `ANTHROPIC_MODEL` | Claude model (default: `claude-sonnet-4-6`) |
| `WEBHOOK_SECRET` | Secret to verify Jira webhook signatures |
| `PORT` | Port to run on (default: `5000`) |
| `FLASK_ENV` | `development` or `production` |
| `FLASK_SECRET_KEY` | Random string for Flask session signing |

#### Getting a Jira API token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**, name it (e.g. "AC Agent"), copy the value
3. Paste it into `JIRA_API_TOKEN` — the associated email goes in `JIRA_EMAIL`

---

## Running the app

```bash
python app.py
```

The web UI is available at http://localhost:5000

For production, use Gunicorn:

```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

---

## Web UI usage

1. Open http://localhost:5000
2. Type a Jira ticket key (e.g. `ENG-42`)
3. Click **Generate AC** or press Enter
4. Copy the generated criteria to your clipboard

---

## Jira webhook integration

### How it works

When configured, Jira calls `POST /webhook/jira` whenever an issue is created or updated. The agent:

1. Verifies the HMAC-SHA256 signature (if `WEBHOOK_SECRET` is set)
2. Extracts the issue key from the payload
3. Fetches the full ticket from Jira
4. Generates acceptance criteria with Claude
5. Logs the result (extend `app.py` to write back to Jira or Slack)

### Configuring the webhook in Jira

1. In your Jira project, go to **Project settings → Webhooks** (or Jira admin → System → Webhooks)
2. Click **Create a WebHook**
3. Set **URL** to `https://your-public-host/webhook/jira`
4. Under **Events**, select **Issue → created** and **Issue → updated**
5. Optionally add a JQL filter (e.g. `project = ENG AND issuetype = Story`)
6. Set the **Secret** field to the same value as your `WEBHOOK_SECRET` env var
7. Save

> **Local testing:** Use [ngrok](https://ngrok.com) to expose your local server:
> ```bash
> ngrok http 5000
> # Use the https://xxxx.ngrok.io URL as your webhook URL in Jira
> ```

### Writing AC back to Jira (extending the webhook handler)

In `app.py`, after `result = _process_ticket(ticket_key)`, add a call to write the AC back as a Jira comment:

```python
# Example: post AC as a comment on the ticket
import requests
from requests.auth import HTTPBasicAuth

requests.post(
    f"{os.environ['JIRA_BASE_URL']}/rest/api/3/issue/{ticket_key}/comment",
    auth=HTTPBasicAuth(os.environ['JIRA_EMAIL'], os.environ['JIRA_API_TOKEN']),
    headers={"Content-Type": "application/json"},
    json={
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": result["acceptance_criteria"]}]
            }]
        }
    }
)
```

---

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web UI |
| `/generate` | POST | Generate AC for a ticket (JSON body: `{"ticket_key": "PROJ-123"}`) |
| `/webhook/jira` | POST | Jira webhook receiver |
| `/health` | GET | Health check |

---

## Troubleshooting

**"Jira authentication failed"**
→ Double-check `JIRA_EMAIL` and `JIRA_API_TOKEN`. The token must belong to the email you provided.

**"Ticket not found"**
→ Confirm the ticket key is correct and the Jira account has permission to view it. Check `JIRA_PROJECT_FILTER` isn't excluding the project.

**Webhook returns 401**
→ The HMAC signature didn't match. Make sure `WEBHOOK_SECRET` in `.env` matches the secret you set in Jira exactly.

**Empty or poor AC output**
→ The ticket description may be sparse. Add more context to the ticket and try again. You can also adjust the system prompt in `src/ac_generator.py`.
