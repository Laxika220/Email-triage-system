
# Email Triage System

An automated customer support pipeline that reads incoming emails, classifies intent and sentiment using an LLM, generates a context-aware reply, and sends it back — with no manual intervention required.

## What it does

1. **Polls an inbox via IMAP** for new, unread emails on a fixed interval.
2. **Classifies each email** using Groq's LLM API — extracting sentiment, intent (order status, complaint, refund request, general inquiry, compliment, or unrelated), order ID, and whether the email contains multiple questions.
3. **Generates a tailored reply** based on the classification — different reply strategies for complaints, multi-question emails, missing order IDs, and general inquiries.
4. **Sends the reply via SMTP**, correctly threaded under the original email using `In-Reply-To` / `References` headers so it appears as a real reply in the customer's inbox, not a disconnected new email.

## Tech stack

| Component        | Technology                          |
|-------------------|--------------------------------------|
| Email retrieval    | IMAP (`imap-tools`)                 |
| Email sending      | SMTP (`smtplib`, Gmail)             |
| LLM classification | Groq API (`openai/gpt-oss-20b`)     |
| LLM reply generation | Groq API                          |
| Config management  | `python-dotenv`                     |
| Language            | Python 3                            |

## Setup

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your own credentials:
   ```bash
   cp .env.example .env
   ```

   You'll need:
   - A **Gmail App Password** (not your regular password) — generate one from your Google Account → Security → App Passwords, with 2FA enabled.
   - A **Groq API key** — available from [console.groq.com](https://console.groq.com).

3. Run the script:
   ```bash
   python triage.py
   ```

   By default it polls every 5 seconds and processes any new unread email received after the script started.

## Configuration

- `DRY_RUN = True` in `triage.py` lets you preview generated replies in the terminal without actually sending anything — useful for testing prompt changes safely.
- `REVIEW_EMAIL_ADDRESS` (optional) BCCs every sent reply to a second inbox, so you can review outgoing replies without watching the terminal.

## Project structure

```
email_triage/
├── triage.py        # main pipeline: IMAP polling, classification, reply generation, SMTP sending
├── __init__.py
└── .env              # credentials (not committed — see .gitignore)
```

## Notes

- Classification uses `temperature=0` for consistency; reply generation uses a higher temperature for more natural phrasing.
- The classifier requests strict JSON output and includes a fallback + one retry if the model returns malformed JSON, so a single bad response never crashes the pipeline.
- Emails with an intent requiring an order ID (order status, complaint, refund request) but no ID found will prompt the customer for it rather than guessing.

## Security

Credentials are loaded from environment variables via `.env`, which is excluded from version control. See `.env.example` for the required variables without real values.

