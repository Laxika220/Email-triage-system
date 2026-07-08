import os
import json
import time
import smtplib
from datetime import date, datetime, timezone
from email.mime.text import MIMEText
from dotenv import load_dotenv
from imap_tools import MailBox, AND
from groq import Groq

load_dotenv()

email_address = os.getenv("GMAIL_ADDRESS")
app_password = os.getenv("GMAIL_APP_PASSWORD")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))  

NEEDS_ORDER_ID = {"order_status", "complaint", "refund_request"}

# Centralized so tone/signature stays consistent across every reply type
SUPPORT_SIGNATURE = "Customer Support Team"


def to_aware_utc(dt):
    """Some email messages report a date with no timezone attached (naive),
    others include one (aware). Python can't compare the two directly, so
    this normalizes any datetime to timezone-aware UTC first."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def analyze_email(email_text, retry=True):
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        max_tokens=500,
        temperature=0,  # deterministic classification -- we want consistency, not creativity
        response_format={"type": "json_object"},  # forces valid JSON output, fixes most parse failures
        messages=[
            {
                "role": "user",
                "content": f"""Analyze this customer email and respond ONLY with JSON in this exact format, no extra text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "intent": "order_status" or "complaint" or "refund_request" or "general_inquiry" or "compliment" or "unrelated",
  "order_id": "the EXACT order ID as written in the email if present, or null. Never invent one.",
  "multi_question": true or false,
  "summary": "one sentence summary of what they want"
}}

Rules for intent:
- "order_status": asking where an order is, delivery date, tracking, processing status.
- "complaint": something is wrong (damaged, missing item, wrong item, not delivered despite tracking saying delivered, product not working).
- "refund_request": asking for money back, or a duplicate/incorrect charge.
- "general_inquiry": questions that aren't about a specific order problem (invoices, coupons, changing an item/size/address before shipping, general questions).
- "compliment": positive feedback with no request attached.
- "unrelated": has nothing to do with an order, product, or account with this store (jokes, spam, newsletters, absurd requests, unrelated topics).

A complaint does not need angry language -- a polite email about a damaged or missing item is still a complaint.
A refund request phrased politely is still "refund_request", not "general_inquiry".
"multi_question" is true if the customer asks more than one distinct question in the same email.

Email:
{email_text}"""
            }
        ]
    )
    raw = response.choices[0].message.content

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if retry:
            print("[WARNING] First analysis wasn't valid JSON, retrying once...")
            return analyze_email(email_text, retry=False)
        print(f"[WARNING] Could not parse LLM response as JSON. Raw response was: {raw!r}")
        # safe fallback so one bad response never crashes the whole pipeline
        return {
            "sentiment": "neutral",
            "intent": "general_inquiry",
            "order_id": None,
            "multi_question": False,
            "summary": "Could not analyze this email automatically.",
        }


def generate_reply(analysis, email_text, customer_name=None):
    intent = analysis["intent"]
    order_id = analysis["order_id"]
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

   
    if intent == "unrelated":
        return (
            f"{greeting} thanks for reaching out! This doesn't look related to an order or "
            f"account with us — could you let us know what you need help with regarding your order?\n\n"
            f"{SUPPORT_SIGNATURE}"
        )

    
    if intent in NEEDS_ORDER_ID and order_id is None:
        return (
            f"{greeting} thank you for contacting us. Could you please share your Order ID "
            f"so we can look into this for you right away?\n\n{SUPPORT_SIGNATURE}"
        )

    
    if analysis["multi_question"]:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            max_tokens=400,
            temperature=0.6,  # some warmth/variation, but still controlled
            messages=[
                {
                    "role": "user",
                    "content": f"""The customer asked multiple questions in this email. Write ONLY the body text of a warm,
professional customer support reply -- no subject line, no placeholder brackets like [Name] or [Company], no signature
block with unfilled fields. Start with "{greeting}". Sign off simply as "{SUPPORT_SIGNATURE}".

Address EACH question as a separate numbered point (1, 2, 3...). Do not merge them into one vague sentence.
Do not invent specific dates, amounts, or facts you don't know -- speak generally ("we'll confirm shortly") where needed.
Acknowledge the customer's specific situation in your first sentence rather than opening generically.

Order ID mentioned: {order_id}
Original email:
{email_text}"""
                }
            ]
        )
        return response.choices[0].message.content

   
    if intent == "compliment":
        return (
            f"{greeting} thank you so much for the kind words! We really appreciate you taking "
            f"the time to share this.\n\n{SUPPORT_SIGNATURE}"
        )

    
    if intent == "general_inquiry":
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            max_tokens=250,
            temperature=0.6,
            messages=[
                {
                    "role": "user",
                    "content": f"""Write ONLY the body text of a short, helpful customer support reply -- no subject line,
no placeholder brackets, no unfilled signature fields. Start with "{greeting}". Sign off simply as "{SUPPORT_SIGNATURE}".

Customer request: {analysis['summary']}
Order ID mentioned: {order_id}
Keep it under 3 sentences. Directly reference what they asked rather than replying generically.
Do not promise specific outcomes you can't confirm -- say it will be looked into / confirmed shortly."""
                }
            ]
        )
        return response.choices[0].message.content

   
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        max_tokens=300,
        temperature=0.6,
        messages=[
            {
                "role": "user",
                "content": f"""Write ONLY the body text of a short, professional customer support reply -- no subject line,
no placeholder brackets like [Name] or [Company], no unfilled signature fields. Start with "{greeting}". Sign off simply as "{SUPPORT_SIGNATURE}".

Intent: {intent}
Order ID mentioned: {order_id}
Customer issue: {analysis['summary']}
Keep it under 4 sentences. Open by acknowledging their specific issue, not a generic greeting.
Be warm and empathetic if this is a complaint -- briefly apologize for the inconvenience before addressing next steps.
Do not promise a specific refund amount or delivery date you don't actually know."""
            }
        ]
    )
    return response.choices[0].message.content


def triage_email(subject, email_text, customer_name=None):
    print("\nAnalyzing email...\n")

    analysis = analyze_email(email_text)

    print(f"Sentiment     : {analysis['sentiment']}")
    print(f"Intent        : {analysis['intent']}")
    print(f"Order ID      : {analysis['order_id']}")
    print(f"Multi-question: {analysis['multi_question']}")
    print(f"Summary       : {analysis['summary']}")

    reply = generate_reply(analysis, email_text, customer_name)
    print(f"\nSuggested reply:\n{reply}\n")
    return reply


def send_reply(to_address, original_subject, reply_body, original_message_id):
    msg = MIMEText(reply_body)
    msg["Subject"] = f"Re: {original_subject}"
    msg["From"] = email_address
    msg["To"] = to_address
    if original_message_id:
        msg["In-Reply-To"] = original_message_id
        msg["References"] = original_message_id
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server: 
        server.login(email_address, app_password)
        server.send_message(msg)


DRY_RUN = False  

if __name__ == "__main__":
    SCRIPT_START_TIME = datetime.now(timezone.utc)
    print(f"Starting triage pipeline. DRY_RUN={DRY_RUN}. Checking every 5 seconds. Press Ctrl+C to stop.\n")
    print(f"Only emails received after {SCRIPT_START_TIME.strftime('%H:%M:%S')} UTC will be processed.\n")

    while True:
        with MailBox("imap.gmail.com").login(email_address, app_password, initial_folder="INBOX") as mailbox:
            all_unseen = mailbox.fetch(criteria=AND(seen=False, date_gte=date.today()), bulk=True)
            new_emails = [msg for msg in all_unseen if to_aware_utc(msg.date) > SCRIPT_START_TIME]

            if not new_emails:
                print(f"[{time.strftime('%H:%M:%S')}] No new emails. Waiting...")

            for msg in new_emails:
                
                if not msg.text or not msg.text.strip():
                    print(f"\n[{time.strftime('%H:%M:%S')}] Skipping email from '{msg.from_}' "
                          f"(subject: '{msg.subject}') -- empty body, nothing to analyze.")
                    continue

                print(f"\n{'='*50}")
                print(f"From: {msg.from_} | Subject: {msg.subject}")
                print(f"{'='*50}")

                # Pull the customer's first name for personalization, if available
                customer_name = None
                if msg.from_values and msg.from_values.name:
                    customer_name = msg.from_values.name.split()[0]

                try:
                    reply = triage_email(msg.subject, msg.text, customer_name)
                except Exception as e:
                    print(f"[ERROR] Failed to process this email, skipping it: {e}")
                    continue

                if DRY_RUN:
                    print("[DRY RUN - not actually sending]")
                else:
                    original_msg_id = msg.headers.get("message-id", ("",))[0]
                    send_reply(msg.from_, msg.subject, reply, original_msg_id)
                    print("[Reply sent!]")

        time.sleep(5)