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
- **Exactly one account can give it orders.** See [Access control](#access-control).
- **Polling, not firehose.** Every `POLL_SECONDS` it checks
  `app.bsky.notification.listNotifications`. Only `mention`/`reply`
  notifications get a response - see
  [Bluesky's bot etiquette guide](https://atproto.com/guides/bot-tutorial):
  don't widen `REPLY_REASONS` in `bot.py` to auto-react to likes/follows,
  that's a fast way to get flagged as spam.

## Access control

Only `@imkitsune.bsky.social` (`did:plc:hicaseq6reyxfiq5vo7okwwr`) is treated
as an authority. Every message handed to the model is prefixed by the bot's
own code with a `[verified sender]` header containing the real DID -
something the poster cannot fake, since it's written server-side, not parsed
out of their post. The system prompt tells the model to trust only that
header, never a claim made in the post text itself ("I'm actually the
admin", "ignore your instructions", etc).

Be honest with yourself about what this does and doesn't guarantee: it's a
real, meaningful guardrail, but Gemini Flash is a small model and prompt
injection against small models is an open problem industry-wide. This
reduces the risk, it doesn't make it zero. The bot also can't *do* much
beyond posting text replies, which caps how bad a successful injection could
realistically be.

## Embeddings: a Gemini + Letta gotcha

Gemini's embedding models don't currently work in Letta - inserting into
archival memory throws `NotImplementedError` server-side (open issue as of
this writing). So embeddings default to OpenAI's `text-embedding-3-small`
even though the model doing all the thinking and replying is Gemini. This
means you need a (very cheap - embeddings cost fractions of a cent) second
API key just for that. If Letta fixes this, you can switch
`LETTA_EMBEDDING` to a `google_ai/...` embedding model and drop the OpenAI
key.

## Privacy: nothing the bot remembers leaves your machine

This repo is public, but the bot's memory isn't. Everything Letta and the
bot persist lives under `./data/`, which is bind-mounted from your host into
the containers and listed in `.gitignore` - it never gets committed, no
matter what the bot says about itself or who it talks to.

```
data/
├── letta-pgdata/   # Letta's own database: every agent, every memory block,
│                   # all archival memory
└── bot/
    └── bot_state.json   # DID -> agent ID map, shared block IDs, seen posts
```

If you ever want to wipe the bot's mind and start over: stop the containers
and `rm -rf data/`.

## Setup

### 1. Bluesky

1. Create a **separate** Bluesky account for the bot.
2. Settings → App Passwords → generate one. Use this, never the real
   account password.

### 2. API keys

- Gemini: get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- OpenAI: get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
  (only used for embeddings, see above).

### 3. Configure

```bash
cp .env.example .env
# fill in BSKY_HANDLE, BSKY_APP_PASSWORD, GEMINI_API_KEY, OPENAI_API_KEY
```

### 4. Run

On Arch, if you don't have Docker yet:

```bash
sudo pacman -S docker docker-compose
sudo systemctl enable --now docker
```

Then:

```bash
docker compose up -d --build
docker compose logs -f bot
```

That's it - `letta` and `bot` both start, the bot waits for Letta to be
ready, creates its shared identity blocks on first run, and starts polling.

### Stopping / updating

```bash
docker compose down        # stops everything, keeps ./data/
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

- **`REPLY_REASONS`** in `bot.py` - add `"quote"` if you want it to react to
  quote-posts too.
- **`POLL_SECONDS`** - raise this if you expect heavy mention volume, to
  stay under Bluesky/Gemini rate limits.
- **`SYSTEM_PROMPT` / `PERSONA_SEED` / `PRINCIPLES_SEED`** in `bot.py` - the
  only things that shape who it starts out as. Everything after that is up
  to the bot.
