"""Fetch transport for scripts/studio_chat.py --fetch: a real uAgent that talks to Studio businesses
with the Agent Chat Protocol (the same messages ASI:One sends), and renders their text and cards.

Agents with an Agentverse mailbox are resolved through the Almanac as usual. Studio businesses that
could not get a mailbox (account limit) are reached at their own Fetch endpoint on this machine.
"""
import asyncio
import json
import os
import queue
import threading
from datetime import datetime, timezone
from uuid import uuid4

os.environ["AGENTVERSE_API_KEY"] = ""  # the CLI customer is a plain uAgent, it never takes an Agentverse slot

from uagents import Agent, Context, Protocol  # noqa: E402
from uagents.resolver import GlobalResolver, Resolver  # noqa: E402
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, TextContent,  # noqa: E402
                                                 chat_protocol_spec)

def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()  # several CLI sessions can run at once


class StudioResolver(Resolver):
    def __init__(self, local: dict[str, str]):
        self.local, self.fallback = local, GlobalResolver()

    async def resolve(self, destination: str):
        if destination in self.local:
            return destination, [self.local[destination]]
        return await self.fallback.resolve(destination)


class FetchClient:
    def __init__(self, local_endpoints: dict[str, str]):
        self.outbox: queue.Queue = queue.Queue()
        self.inbox: queue.Queue = queue.Queue()
        self.local, self._ready = local_endpoints, threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(30)

    def _build(self) -> Agent:
        agent = Agent(name="studio-cli-customer", seed="lazarus studio cli customer xxxxxxxx", port=PORT,
                      endpoint=[f"http://127.0.0.1:{PORT}/submit"], resolve=StudioResolver(self.local), log_level="ERROR")
        proto = Protocol(spec=chat_protocol_spec)

        @proto.on_message(ChatMessage)
        async def got(ctx: Context, sender: str, msg: ChatMessage):
            await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
            for c in msg.content:
                self.inbox.put(("msg", sender, c.model_dump()))

        @proto.on_message(ChatAcknowledgement)
        async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
            self.inbox.put(("ack", sender, None))

        @agent.on_interval(period=0.3)
        async def flush(ctx: Context):
            while not self.outbox.empty():
                to, text = self.outbox.get()
                await ctx.send(to, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                               content=[TextContent(type="text", text=text)]))

        agent.include(proto)
        return agent

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.agent = self._build()  # uAgents binds to the loop that exists when it is built
        self.address = self.agent.address
        self._ready.set()
        loop.run_until_complete(self.agent.run_async())

    def ask(self, to: str, text: str, timeout: float = 90.0):
        """Yields ("ack"|"msg", content) until the reply looks complete or the timeout passes."""
        while not self.inbox.empty():
            self.inbox.get()
        self.outbox.put((to, text))
        got_text, deadline = False, timeout
        while True:
            try:
                kind, sender, content = self.inbox.get(timeout=deadline)
            except queue.Empty:
                return
            yield kind, content
            if kind == "msg":
                if content.get("type") == "metadata":
                    return
                got_text, deadline = True, 4.0  # a card usually follows the text within a second


def render(content: dict) -> tuple[list[str], list[dict]]:
    """Plain lines plus the card's buttons ({label, selection}) for a chat content item."""
    if content.get("type") == "text":
        return [content.get("text", "")], []
    if content.get("type") == "metadata":
        md = content.get("metadata") or {}
        try:
            card = json.loads(md.get("card_payload", "{}"))
        except ValueError:
            return [json.dumps(md)[:400]], []
        lines, buttons = [f"[{md.get('card_kind', 'card')}] {card.get('title', '')}" + (f"  — {card['subtitle']}" if card.get("subtitle") else "")], []
        for r in card.get("summary_rows") or []:
            lines.append(f"  {r.get('label', ''):<26} {r.get('value', '')}")
        for it in card.get("items") or []:
            b = it.get("primary_cta")
            if b:
                buttons.append(b)
            lines.append(f"  [{len(buttons)}] {it.get('title', ''):<32} {it.get('subtitle', '')}  ({b['label'] if b else ''})")
        for b in card.get("ctas") or []:
            buttons.append(b)
        if card.get("ctas"):
            lines.append("  " + "  ".join(f"[{i}] {b['label']}" for i, b in enumerate(buttons, 1) if b in card["ctas"]))
        return lines, buttons
    return [json.dumps(content)[:300]], []
