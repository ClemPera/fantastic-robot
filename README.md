# Bluesky bot with a self-shaping Letta identity

A small Gemini-Flash-powered entity that lives on Bluesky, replies to
mentions/replies, and figures out its own personality over time instead of
being handed a fixed one. Built on [Letta](https://docs.letta.com).

## How it works

- **One Letta agent per Bluesky account it talks to.** Letta agents are
  stateful and persist their own history server-side, so we only ever send
  the new message, never the full conversation.
- **One identity, not many.** Each per-user agent shares two memory blocks -
  `persona` and `principles` - across every conversation, anywhere. The bot
  can edit these about itself whenever it decides something is genuinely
  true of it; until it does, the existing text is who it is. Nothing forces
  a rewrite on every run, so its personality only drifts when it chooses to
  drift it. Each agent also keeps a private `human` block - what it knows
  about that one specific person.
- **It's small and dumb on purpose.** Gemini Flash has a tiny context
  window, so the system prompt leans hard on it using Letta's
  `archival_memory_search` / `archival_memory_insert` tools rather than
  trusting anything to stay in-context. Save liberally, forget nothing on
  purpose.
- **Exactly one account can give it orders** - see [Access control](#access-control)
  for what that does and doesn't actually guarantee.
- **Polling, not firehose.** Every `POLL_SECONDS` it checks
  `app.bsky.notification.listNotifications`. Only `mention`/`reply`
  notifications get a response - see
  [Bluesky's bot etiquette guide](https://atproto.com/guides/bot-tutorial):
  don't widen `REPLY_REASONS` in `bot.py` to auto-react to likes/follows,
  that's a fast way to get flagged as spam.

## Access control - and its real limits

Only `@imkitsune.bsky.social` (`did:plc:hicaseq6reyxfiq5vo7okwwr`) is meant
to be treated as an authority. Here's exactly how that's enforced, and
where it stops being a hard guarantee:

A poster cannot literally produce the verified-sender block the model is
told to trust, because it's written by the bot's own code and always sits
first in the message, never parsed out of the post. What a poster *can* do
is write a post whose text **looks like** a verified-sender block,
hoping the model gets confused about which one is real - that's the actual
attack surface, and it's a real one against any LLM, especially a small
one. To raise the bar, the real header uses a random secret marker
(generated once, stored in `bot_state.json`, never revealed in replies) -
a forged block in someone's post text can't reproduce that marker without
already knowing it. That meaningfully reduces the risk. It does not make it
zero - there's no prompt-based scheme that turns an LLM into a hard security
boundary, and a sufficiently clever attacker working against a small model
might still get somewhere with this.

Worth being clear-eyed about: today, nothing in this codebase actually
*does* anything different for admin vs non-admin beyond what the model
itself chooses to do - there's no real privileged tool gated on it. So the
worst case of a successful bypass right now is the bot saying something
embarrassing in a public reply, not an actual unauthorized action. If you
ever add a tool that does something that matters (wiping memory, posting
arbitrary content on a schedule, anything destructive), gate *that* in code
with a `did == ADMIN_DID` check - never rely on the model's judgment alone
for anything with real consequences.

## Embeddings run locally, not on a paid API

Gemini's embedding models don't currently work in Letta - inserting into
archival memory throws `NotImplementedError` server-side (open upstream
issue). Rather than fall back to OpenAI, embeddings run locally via
[Ollama](https://ollama.com), which `docker-compose.yml` brings up and
pulls a model into automatically on first run. Default is `all-minilm`
(~46MB) - light enough for a Raspberry Pi. If you have RAM/storage to
spare and want noticeably better recall, switch to `nomic-embed-text`
(~274MB): update `LETTA_EMBEDDING` in `.env` *and* the model name in the
`ollama-pull` service in `docker-compose.yml`, then `docker compose up -d --build`.

## Running this on a Raspberry Pi

Both `letta/letta` and `ollama/ollama` publish `arm64` images, so this runs
natively on a Pi 4/5 (no architecture is amd64-only here). On a 4GB Pi,
rough resident memory once everything's warmed up:

| service | approx. RAM |
|---|---|
| Postgres (inside the `letta` container) | 100-200MB |
| Letta server | 300-600MB |
| Ollama daemon + `all-minilm` | 150-300MB |
| bot | 50-100MB |

That leaves headroom in 4GB for the OS, but not a lot if something spikes -
a couple of things worth doing on the Pi specifically:

- **Add swap** if you haven't already (`dphys-swapfile` on Raspberry Pi OS).
  Cheap insurance against an OOM kill during a Letta server restart or model
  pull.
- **Watch it for the first day**: `docker stats` while it's running, and
  bump `POLL_SECONDS` up if memory pressure shows up under load.
- Skip `nomic-embed-text` on a 4GB board unless you've confirmed headroom -
  `all-minilm` is the safer default here.

## Privacy: nothing the bot remembers leaves your machine

This repo is public, but the bot's memory isn't. Everything Letta, Ollama,
and the bot persist lives under `./data/`, which is bind-mounted from your
host into the containers and listed in `.gitignore` - it never gets
committed, no matter what the bot says about itself or who it talks to.

```
data/
├── letta-pgdata/   # Letta's own database: every agent, every memory block,
│                   # all archival memory
├── ollama/         # the downloaded embedding model
└── bot/
    └── bot_state.json   # DID -> agent ID map, shared block IDs, seen posts, nonce
```

If you ever want to wipe the bot's mind and start over: stop the containers
and `rm -rf data/`.

## Setup

### 1. Bluesky

1. Create a **separate** Bluesky account for the bot.
2. Settings → App Passwords → generate one. Use this, never the real
   account password.

### 2. API key

Gemini only: get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Embeddings are local (see above), so that's the only key you need.

### 3. Configure

```bash
cp .env.example .env
# fill in BSKY_HANDLE, BSKY_APP_PASSWORD, GEMINI_API_KEY
```

### 4. Run

On Arch, if you don't have Docker yet:

```bash
sudo pacman -S docker docker-compose
sudo systemctl enable --now docker
```

On Raspberry Pi OS (64-bit), see [Docker's install guide](https://docs.docker.com/engine/install/raspberry-pi-os/).

Then, on either:

```bash
docker compose up -d --build
docker compose logs -f bot
```

`ollama`, `letta`, and `bot` all start; `ollama-pull` fetches the embedding
model once and exits; `bot` waits for both before it starts polling.

### Stopping / updating

```bash
docker compose down            # stops everything, keeps ./data/
docker compose up -d --build   # rebuild after pulling code changes
```

## Watching it think

Connect the Letta ADE (`app.letta.com` → "add a self-hosted server") to
`http://localhost:8283` (password protection is off by default here - add
`SECURE=true` + `LETTA_SERVER_PASSWORD` env vars to the `letta` service in
`docker-compose.yml` if you expose this beyond localhost). You can watch its
`persona` and `principles` blocks update live, and search its archival
memory directly.

## Things you'll likely want to tweak

- **Polling vs firehose**: polling every 30s is simple and fine for normal
  mention volume. If you want true real-time, swap the loop for a Jetstream
  / firehose subscription instead - more moving parts, not included here.
- **Rate limits**: both Bluesky and Gemini have rate limits. If you expect
  heavy mention volume, raise `POLL_SECONDS` or add backoff.
- **`REPLY_REASONS`** in `bot.py`: only `mention`/`reply` trigger a response
  by default. Add `"quote"` if you want it to react to quote-posts too -
  not included by default since a quote doesn't necessarily tag the bot in
  text.
- **`SYSTEM_PROMPT` / `PERSONA_SEED` / `PRINCIPLES_SEED`** in `bot.py` - the
  only things that shape who it starts out as. Everything after that is up
  to the bot.
