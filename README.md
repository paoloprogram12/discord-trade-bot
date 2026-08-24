# Discord Trade Bot

A Discord bot that tracks the Asia, London, and New York trading session hours and automatically posts `@everyone` alerts in a designated channel when each session opens and closes (weekdays only).

## Features

- Monitors three trading sessions on their local market hours:
  - **Asia** — Asia/Tokyo, 09:00–15:00
  - **London** — Europe/London, 08:00–16:30
  - **New York** — US/Eastern, 09:30–16:00
- Posts an open/close ping to a configured channel within a minute of each session boundary, skipping weekends.
- `!test` command to verify the bot can post to the channel.

## Configuration

The bot reads its configuration from environment variables (loaded via `.env` locally):

| Variable | Description |
| --- | --- |
| `DISCORD_TOKEN` | Bot token from the [Discord Developer Portal](https://discord.com/developers/applications). |
| `CHANNEL_ID` | ID of the channel the bot should post session alerts to. |

The bot requires the **Message Content** intent enabled for the application in the Discord Developer Portal.

## Running locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in DISCORD_TOKEN and CHANNEL_ID
python bot.py
```

## Deploying on Railway

This bot runs as a background **worker** service (it doesn't listen on an HTTP port), which Railway supports natively.

1. **Create a project** on [Railway](https://railway.app) and choose **Deploy from GitHub repo**, selecting this repository.
2. Railway will detect the Python project via `requirements.txt` and build it using Nixpacks automatically — no Dockerfile needed.
3. **Set the start command.** In the service's Settings → Deploy, set the start command to:
   ```
   python bot.py
   ```
4. **Add environment variables.** In the service's Variables tab, add:
   - `DISCORD_TOKEN`
   - `CHANNEL_ID`
5. **Deploy.** Railway will install dependencies from `requirements.txt` and start the bot. Check the Deploy Logs for `Logged in as <bot_name>` to confirm it connected successfully.
6. Because this is a long-running process (not a web server), make sure the service is **not** configured to expect a health-checked HTTP port — leave the Railway networking/port settings untouched.

Any push to the connected branch will trigger a new deploy automatically.
