"""Bluesky bot powered by Letta agents with persistent, per-user memory.

Architecture:
  - One Letta agent per Bluesky DID (account). Letta agents are stateful and
    persist their own conversation history + memory blocks server-side, so we
    only ever send the *new* message, never the full history.
  - The agent's "human" memory block holds what the bot knows about that
    specific person. Letta edits this block itself, automatically, as it
    chats - that's its built-in self-editing memory, no extra setup needed.
  - We poll app.bsky.notification.listNotifications on an interval. Real-time
    push (the Jetstream firehose) is possible too, but polling is simpler and
    is what Bluesky's own bot guide recommends for most bots.
"""

import logging
import os
import time

import grapheme
from atproto import Client, models
from dotenv import load_dotenv
from letta_client import Letta

from memory import BotState

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bsky-letta-bot")

BSKY_HANDLE = os.environ["BSKY_HANDLE"]
BSKY_APP_PASSWORD = os.environ["BSKY_APP_PASSWORD"]

# Pick ONE: LETTA_BASE_URL for a self-hosted server, LETTA_API_KEY for Letta Cloud
LETTA_BASE_URL = os.environ.get("LETTA_BASE_URL")
LETTA_API_KEY = os.environ.get("LETTA_API_KEY")
LETTA_MODEL = os.environ.get("LETTA_MODEL", "openai/gpt-4o-mini")
LETTA_EMBEDDING = os.environ.get("LETTA_EMBEDDING", "openai/text-embedding-3-small")

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))
STATE_FILE = os.environ.get("STATE_FILE", "bot_state.json")

# Bluesky's hard limit is 300 graphemes. We leave headroom so the model's
# natural sign-off / punctuation doesn't get cut off mid-word.
MAX_POST_GRAPHEMES = 280

PERSONA = os.environ.get(
    "BOT_PERSONA",
    "I am a Bluesky bot. I reply to mentions and replies directed at me. "
    "I keep replies under 280 characters, friendly and to the point. "
    "I remember what each person has told me across our past conversations "
    "and use that naturally, without being creepy about it.",
)

# Only reply to direct interactions. Liking/reposting/following on your own
# initiative is against Bluesky bot etiquette unless a user opts in by
# tagging you - see https://atproto.com/guides/bot-tutorial
REPLY_REASONS = {"mention", "reply"}


def build_letta_client() -> Letta:
    if LETTA_BASE_URL:
        return Letta(base_url=LETTA_BASE_URL)
    if LETTA_API_KEY:
        return Letta(api_key=LETTA_API_KEY)
    raise RuntimeError(
        "Set either LETTA_BASE_URL (self-hosted Docker server) or "
        "LETTA_API_KEY (Letta Cloud) in your .env file."
    )


def get_or_create_agent(letta: Letta, state: BotState, did: str, handle: str) -> str:
    """One persistent Letta agent per Bluesky account we talk to."""
    agent_id = state.get_agent_id(did)
    if agent_id:
        return agent_id

    agent = letta.agents.create(
        model=LETTA_MODEL,
        embedding=LETTA_EMBEDDING,
        memory_blocks=[
            {"label": "persona", "value": PERSONA},
            {
                "label": "human",
                "value": f"Bluesky handle: @{handle}. DID: {did}. No other facts learned yet.",
                "description": (
                    "What I know about this specific Bluesky user. I keep "
                    "this updated myself as I learn new things about them."
                ),
            },
        ],
    )
    state.save_agent_id(did, agent.id)
    log.info("Created new Letta agent %s for @%s", agent.id, handle)
    return agent.id


def truncate_graphemes(text: str, limit: int) -> str:
    if grapheme.length(text) <= limit:
        return text
    return grapheme.slice(text, 0, limit - 1) + "…"


def ask_agent(letta: Letta, agent_id: str, text: str) -> str:
    response = letta.agents.messages.create(
        agent_id=agent_id,
        messages=[{"role": "user", "content": text}],
    )
    parts = [m.content for m in response.messages if m.message_type == "assistant_message"]
    reply = " ".join(parts).strip() or "Sorry, I'm not sure how to respond to that."
    return truncate_graphemes(reply, MAX_POST_GRAPHEMES)


def build_reply_refs(notif) -> "models.AppBskyFeedPost.ReplyRef":
    """root/parent refs for the new post. If the mentioning post is itself a
    reply, walk up to the real thread root instead of re-rooting the thread."""
    parent = models.create_strong_ref(notif)
    existing_reply = getattr(notif.record, "reply", None)
    root = existing_reply.root if existing_reply is not None else parent
    return models.AppBskyFeedPost.ReplyRef(parent=parent, root=root)


def handle_notification(bsky: Client, letta: Letta, state: BotState, notif) -> None:
    if notif.reason not in REPLY_REASONS:
        return
    if state.has_seen(notif.uri):
        return

    text = getattr(notif.record, "text", "") or ""
    handle = notif.author.handle
    did = notif.author.did
    log.info("Handling %s from @%s: %r", notif.reason, handle, text)

    agent_id = get_or_create_agent(letta, state, did, handle)
    reply_text = ask_agent(letta, agent_id, text)

    bsky.send_post(reply_text, reply_to=build_reply_refs(notif))
    state.mark_seen(notif.uri)
    log.info("Replied to @%s: %r", handle, reply_text)


def run() -> None:
    bsky = Client()
    bsky.login(BSKY_HANDLE, BSKY_APP_PASSWORD)
    log.info("Logged in to Bluesky as @%s", BSKY_HANDLE)

    letta = build_letta_client()
    state = BotState(STATE_FILE)

    log.info("Polling notifications every %ss", POLL_SECONDS)
    while True:
        try:
            last_seen_at = bsky.get_current_time_iso()
            response = bsky.app.bsky.notification.list_notifications()
            for notif in response.notifications:
                if notif.is_read:
                    continue
                try:
                    handle_notification(bsky, letta, state, notif)
                except Exception:
                    log.exception("Failed to handle notification %s", notif.uri)
            bsky.app.bsky.notification.update_seen({"seen_at": last_seen_at})
        except Exception:
            log.exception("Error during polling loop")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
