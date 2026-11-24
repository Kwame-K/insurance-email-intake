# Insurance Email Intake

Captures broker emails (`.eml` files or HTTP) and forwards them to the
underwriting agent's `POST /extract-and-underwrite`. It contains no underwriting
logic. Processed emails are stored once (idempotent on `Message-ID`).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| POST | `/v1/emails/eml` | Raw RFC 822 body (`message/rfc822`) |
| POST | `/v1/emails/text` | JSON `{subject, body, sender?, overrides?}` |
| POST | `/v1/emails/{source_id}/complete` | Add missing fields to a pending email |
| GET | `/v1/emails`, `/v1/emails/{source_id}` | Stored results |
| POST | `/v1/inbox/scan` | Process the inbox folder once |

An optional `<name>.overrides.json` next to `<name>.eml` supplies fields the
extractor cannot provide (for example `mfa_enabled`).

PDF attachments are listed but not processed (contract v1 is text-only).
