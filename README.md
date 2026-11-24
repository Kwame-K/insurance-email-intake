# Insurance Email Intake

Accepts broker emails as `.eml` files or HTTP submissions and forwards their text to the Underwriting Agent's `POST /extract-and-underwrite` endpoint. It stores processing results and is idempotent on `Message-ID`. It does not make underwriting decisions.

This service is part of the [Insurance Agentic Platform](https://github.com/Kwame-K/insurance-agentic-platform). The [Underwriting UI](https://github.com/Kwame-K/insurance-underwriting-ui) uses its API to submit email content and display stored intake results.

> Use synthetic emails for local demonstrations. The v1 contract processes text only: PDF attachments are listed but not processed.

## Workflow

```text
.eml file or submitted email text
    ↓
Email Intake
    ↓
Underwriting Agent → POST /extract-and-underwrite
    ↓
Stored intake result → HTTP API / Underwriting UI
```

Underwriting fields that the extractor cannot supply can be passed as explicit `overrides`. For a file named `broker-submission.eml` in the inbox folder, place `broker-submission.overrides.json` alongside it to provide those fields.

Example sidecar:

```json
{
  "mfa_enabled": true
}
```

Supply values only when they are known. An override is an additional input to underwriting, not an approval or a substitute for missing evidence.

## Run with the Platform

Clone this repository beside `insurance-agentic-platform` and the other application repositories. Follow the [platform setup](https://github.com/Kwame-K/insurance-agentic-platform), then run from the platform repository:

```bash
docker compose up --build -d
curl -f http://127.0.0.1:8004/health
```

| Setting | Value in the platform |
|---|---|
| Compose service name | `email-intake` |
| Host API address | `http://127.0.0.1:8004` |
| `UNDERWRITING_BASE_URL` | `http://underwriting-agent:8002` |
| `UNDERWRITING_TIMEOUT_SECONDS` | 120 by default; set `EMAIL_INTAKE_TIMEOUT_SECONDS` in the platform environment to override it. |
| `INBOX_DIR` | `/app/data/inbox`, mounted read-only from this repository's `data/inbox/` directory. |
| `STATE_DIR` | `/app/data/state`, backed by the `email_intake_state` named volume. |
| `WATCH_ENABLED` | `true` in the platform. |
| `WATCH_INTERVAL_SECONDS` | `10` in the platform. |

The folder watcher reads files from the mounted inbox. Place `.eml` files and optional sidecars in `data/inbox/` on the host, not inside the read-only container mount. You can also request a scan explicitly through the API.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Check intake API liveness. |
| POST | `/v1/emails/eml` | Submit raw RFC 822 email content with `Content-Type: message/rfc822`. |
| POST | `/v1/emails/text` | Submit JSON with `subject` and `body`, plus optional `sender` and `overrides`. |
| POST | `/v1/emails/{source_id}/complete` | Add missing information to a pending intake result. |
| GET | `/v1/emails` | List stored intake results. |
| GET | `/v1/emails/{source_id}` | Retrieve one stored intake result. |
| POST | `/v1/inbox/scan` | Process the inbox folder once. |

### Submit an `.eml` File

```bash
curl -i -X POST http://127.0.0.1:8004/v1/emails/eml \
  -H 'Content-Type: message/rfc822' \
  --data-binary @broker-submission.eml
```

This sends the raw email as the request body. To use a sidecar file, place the email and its sidecar in the watched inbox instead.

### Submit Email Text

```bash
curl -i -X POST http://127.0.0.1:8004/v1/emails/text \
  -H 'Content-Type: application/json' \
  -d '{
    "subject": "Synthetic cyber insurance submission",
    "body": "A Montreal software company with 18 employees and annual revenue of CAD 2,000,000 is seeking cyber insurance.",
    "sender": "broker@example.com",
    "overrides": {
      "mfa_enabled": true,
      "requested_limit_cad": 1000000,
      "requested_retention_cad": 25000
    }
  }'
```

This is an example of the intake contract, not a guarantee that the submission contains everything required for underwriting.

### Scan the Inbox and Inspect Results

```bash
curl -i -X POST http://127.0.0.1:8004/v1/inbox/scan
curl -i http://127.0.0.1:8004/v1/emails
```

Use a returned `source_id` to retrieve an individual intake result. For a pending record, the `/complete` endpoint is available to add missing information. A stored intake record is not necessarily a stored underwriting decision.

## Optional Mail Configuration

The platform exposes IMAP polling and SMTP reply settings, but leaves both disabled by default. Neither is needed for local `.eml` files or HTTP submissions.

| Area | Settings exposed by the platform |
|---|---|
| IMAP toggle | `IMAP_ENABLED` |
| IMAP connection | `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_FOLDER` |
| IMAP polling and filtering | `IMAP_POLL_INTERVAL_SECONDS`, `IMAP_ALLOWED_SENDERS` |
| SMTP reply configuration | `SMTP_REPLY_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `REPLY_LANGUAGE` |

The Compose defaults are `imap.gmail.com:993`, folder `INBOX`, and a 30-second polling interval for IMAP; `smtp.gmail.com:465` and reply language `en` for SMTP. Keep mailbox credentials out of version control. The presence of these settings does not mean mailbox polling or replies are enabled in the default demo.

## Persistence and Limitations

- Email processing is idempotent on `Message-ID`.
- Intake state persists across ordinary platform restarts in `email_intake_state`. Running `docker compose down -v` from the platform removes that state.
- PDF attachments are listed but are not parsed or sent for OCR.
- The service does not own underwriting, pricing, or review decisions. See the [Underwriting Agent](https://github.com/Kwame-K/underwriting-agent) for those contracts.
