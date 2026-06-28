# Bluesky bot with Letta memory

A bot that reads mentions/replies on Bluesky, generates a response through a
[Letta](https://docs.letta.com) agent, and remembers each person it talks to
across conversations - one persistent Letta agent per Bluesky account (DID).

## How it works

- Every `POLL_SECONDS` it calls `app.bsky.notification.listNotifications`.
- For each unread `mention` or `reply` notification, it looks up (or creates)
  a dedicated Letta agent for that person's DID.
- It sends the post text to that agent. Letta keeps the full history and
  self-edits its own "human" memory block as it learns things about that
  person - you don't need to manage that yourself.
- The agent's reply gets truncated to a safe length (grapheme-aware, since
  Bluesky's 300-char limit counts graphemes, not Python string length) and
  posted as a reply in the same thread.
- A small JSON file (`bot_state.json`) tracks DID → agent ID and which
  notification URIs have already been answered, so restarts don't double-post.

Only `mention` and `reply` notifications trigger a response. Per
[Bluesky's own bot guidance](https://atproto.com/guides/bot-tutorial), a bot
should only interact when a user has opted in by tagging it - don't widen
`REPLY_REASONS` in `bot.py` to auto-reply to likes/follows etc, that's a good
way to get flagged as spam.

## 1. Bluesky setup

1. Create a **separate** Bluesky account for the bot (don't use your own).
2. In that account: Settings → App Passwords → generate one. Use this, never
   the real account password.

## 2. Letta setup

You need a running Letta server. Two options:

### Option A - self-host with Docker (free, runs on your machine)

On Arch:

```bash
sudo pacman -S docker docker-compose
sudo systemctl enable --now docker
```

Then run the server, with whichever LLM provider key you have:

```bash
docker run -d --name letta-server \
  -v ~/.letta/.persist/pgdata:/var/lib/postgresql/data \
  -p 8283:8283 \
  -e OPENAI_API_KEY="sk-..." \
  letta/letta:latest
```

(Swap `OPENAI_API_KEY` for `ANTHROPIC_API_KEY` if you want Claude models -
note Anthropic doesn't provide embedding models, so you'd still need an
`OPENAI_API_KEY` set too just for `LETTA_EMBEDDING`, or run an embedding
model locally.)

Check it's up: `curl http://localhost:8283/v1/health`

In `.env`, set `LETTA_BASE_URL=http://localhost:8283` and leave `LETTA_API_KEY` unset.

### Option B - Letta Cloud

Skip Docker, get an API key from your Letta Cloud account, set
`LETTA_API_KEY=...` in `.env` and leave `LETTA_BASE_URL` unset.

## 3. Run the bot

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your real values
python3 bot.py
```

## 4. Keep it running

For anything beyond testing, run it as a systemd user service instead of
leaving a terminal open:

```ini
# ~/.config/systemd/user/bsky-letta-bot.service
[Unit]
Description=Bluesky Letta bot

[Service]
WorkingDirectory=/path/to/bsky-letta-bot
ExecStart=/path/to/bsky-letta-bot/.venv/bin/python3 bot.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now bsky-letta-bot
journalctl --user -u bsky-letta-bot -f
```

## Notes / things you'll likely want to tweak

- **Polling vs firehose**: polling every 30s is simple and fine for normal
  mention volume. If you want true real-time, swap the loop for a Jetstream
  / firehose subscription instead - more moving parts, not included here.
- **Inspecting agent memory**: connect the Letta ADE (`app.letta.com`, "add a
  self-hosted server") to `http://localhost:8283` to watch each user's memory
  blocks update live as the bot chats with them.
- **Rate limits**: both Bluesky and your LLM provider have rate limits. If
  you expect heavy mention volume, raise `POLL_SECONDS` or add backoff.
- **Quotes**: not handled by default since a quote-post doesn't necessarily
  tag the bot in text. Add `"quote"` to `REPLY_REASONS` in `bot.py` if you
  want that behavior too.
