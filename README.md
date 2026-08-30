# AI Voice Sales Agent

An AI-powered voice sales agent built with FastAPI. The system places/receives calls, converts speech to text, runs an AI sales conversation flow with intent classification and lead qualification, and triggers follow-up actions (WhatsApp, callbacks) based on lead outcome (hot/warm/cold).

## Status

- **Phase 1–6:** Complete and passed regression testing (core agent, lead qualification, intent classification, mock telephony/STT/TTS, SQLite persistence, WhatsApp/callback actions).
- **Phase 7 (in progress):** Real Twilio voice integration and Railway production deployment.

## Features

- FastAPI backend with modular routers (calls, webhooks, WhatsApp, scheduler, health)
- AI sales agent with configurable prompts, intent detection, and lead qualification
- Hot / warm / cold lead classification
- Pluggable telephony provider abstraction — supports `MockTelephonyProvider` (for local dev/testing) and `TwilioTelephonyProvider` (for production calls)
- Mock and real speech-to-text / text-to-speech pipelines
- SQLite persistence for leads and conversation history
- WhatsApp messaging and callback scheduling actions
- Twilio voice webhook / TwiML endpoints for real call handling

## Project Structure

```
ai-voice-sales-agent/
│
├── app/
│   ├── main.py                  # FastAPI app entrypoint, router registration
│   │
│   ├── api/                     # HTTP route handlers
│   │   ├── calls.py
│   │   ├── webhooks.py
│   │   ├── whatsapp.py
│   │   ├── scheduler.py
│   │   └── health.py
│   │
│   ├── core/                    # App-wide config, models, shared state
│   │   ├── config.py
│   │   ├── models.py
│   │   └── state.py
│   │
│   ├── voice/                   # Telephony, STT, TTS, conversation flow
│   │   ├── telephony.py
│   │   ├── speech_to_text.py
│   │   ├── text_to_speech.py
│   │   └── conversation.py
│   │
│   ├── ai/                      # Sales agent logic
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── intent.py
│   │   ├── qualification.py
│   │   ├── classification.py
│   │   └── context.py
│   │
│   ├── actions/                 # Post-call actions
│   │   ├── whatsapp.py
│   │   ├── callback.py
│   │   ├── followup.py
│   │   └── lead_actions.py
│   │
│   ├── storage/                 # Persistence layer
│   │   ├── database.py
│   │   └── repository.py
│   │
│   └── utils/
│       ├── datetime_parser.py
│       ├── logger.py
│       └── helpers.py
│
├── data/
│   ├── leads/
│   └── conversations/
│
├── tests/
│   ├── test_classification.py
│   ├── test_qualification.py
│   ├── test_datetime_parser.py
│   ├── test_whatsapp.py
│   └── test_webhooks.py
│
├── assets/
│   ├── resume.pdf
│   └── architecture.png
│
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── README.md
└── railway.json
```

## Requirements

- Python 3.10+
- pip
- A Twilio account with a verified phone number (for Phase 7 real call testing)

## Setup

1. Clone the repository:
   ```bash
   git clone <your-repo-url>
   cd ai-voice-sales-agent
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Copy the example environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```

## Environment Variables

| Variable | Description |
|---|---|
| `BUSINESS_NAME` | Name of the business the agent represents |
| `TARGET_PHONE_NUMBER` | Number the agent will call (test number during Phase 7 self-test, real target afterward) |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | Twilio phone number used to place calls |
| `PUBLIC_BASE_URL` | Public HTTPS URL (Railway deployment URL) used for Twilio webhook callbacks |
| `PORT` | Provided automatically by Railway at runtime |

> Secrets are never hard-coded. All credentials are loaded from environment variables and `.env` is excluded from version control.

## Running Locally

```bash
python3 -m uvicorn app.main:app --reload
```

The app will be available at `http://127.0.0.1:8000`.

## Running Tests

```bash
python3 -m pytest tests/
```

## Deployment (Railway)

This project is deployed exclusively on [Railway](https://railway.app). No other hosting configuration (e.g., Render) is maintained.

Production start command:

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Deployment configuration is defined in `railway.json`.

## Telephony Providers

The application uses a provider abstraction so telephony can be swapped without touching core agent logic:

- **`MockTelephonyProvider`** — used for local development and Phase 1–6 testing; no real calls are placed.
- **`TwilioTelephonyProvider`** — used in production; places and receives real calls via Twilio's Voice API and TwiML webhooks.

## Roadmap

- [x] Phase 1–6: Core agent, qualification, classification, mock providers, persistence, actions
- [ ] Phase 7: Real Twilio voice integration + Railway production deployment
- [ ] Post-launch: Switch `TARGET_PHONE_NUMBER` from self-test number to final assignment number

## License

Proprietary — internal project. Do not distribute without permission.