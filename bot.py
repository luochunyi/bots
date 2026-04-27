#!/usr/bin/env python3
"""
ARC Raiders Map Condition Discord Bot
Fetches and posts map condition schedules to a Discord channel
"""

import os
import time
import logging
from typing import List, Dict, Optional

import aiohttp
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0))

# Constants
EVENTS_API_URL = 'https://metaforge.app/api/arc-raiders/events-schedule'
TRADERS_API_URL = 'https://metaforge.app/api/arc-raiders/traders'
ITEMS_API_URL = 'https://metaforge.app/api/arc-raiders/items'

RARITY_EMOJI = {
    'Common': '⬜',
    'Uncommon': '🟩',
    'Rare': '🟦',
    'Epic': '🟪',
    'Legendary': '🟧',
}


def in_bot_channel():
    """Check decorator: only allow commands in the configured channel."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.channel.id != DISCORD_CHANNEL_ID:
            return False
        return True
    return commands.check(predicate)


class ARCRaidersAPI:
    """Handles fetching ARC Raiders data via aiohttp (non-blocking)."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def fetch_map_conditions(self) -> Optional[List[Dict]]:
        """Fetch event schedule from the Metaforge API."""
        try:
            async with self.session.get(EVENTS_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
            events = data.get('data', [])
            logger.info(f"Successfully fetched {len(events)} events")
            return events
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return None

    async def fetch_traders(self) -> Optional[Dict[str, List[Dict]]]:
        """Fetch trader inventory data from the Metaforge API."""
        try:
            async with self.session.get(TRADERS_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
            traders = data.get('data', {})
            logger.info(f"Successfully fetched traders: {list(traders.keys())}")
            return traders
        except Exception as e:
            logger.error(f"Error fetching traders: {e}")
            return None

    async def fetch_items(self, query: str) -> Optional[Dict]:
        """Search items by name via the Metaforge API."""
        try:
            params = {'search': query[:100], 'limit': 50, 'includeComponents': 'true'}
            async with self.session.get(ITEMS_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
            total = data.get('pagination', {}).get('total', 0)
            logger.info(f"Item search '{query}' returned {total} results")
            return data
        except Exception as e:
            logger.error(f"Error fetching items: {e}")
            return None


class ConditionBot(commands.Bot):
    """Discord bot for posting ARC Raiders map conditions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_id = DISCORD_CHANNEL_ID
        self.current_pin: Optional[discord.Message] = None
        self.current_pin_verified: bool = False
        self.schedule_message: Optional[discord.Message] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[ARCRaidersAPI] = None

    async def setup_hook(self):
        """Called once before the bot connects — create shared aiohttp session."""
        self.http_session = aiohttp.ClientSession()
        self.api = ARCRaidersAPI(self.http_session)
        await self.add_cog(ConditionCommands(self))

    async def close(self):
        """Clean up the aiohttp session on shutdown."""
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f'Logged in as {self.user}')

        channel = self.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Could not find channel with ID {self.channel_id}")
            return

        try:
            await channel.guild.me.edit(nick="SuckBot.69")
            logger.info("Set server nickname to SuckBot.69")
        except discord.Forbidden:
            logger.warning("Missing permissions to change nickname")

        logger.info(f"Using channel: #{channel.name}")

        perms = channel.permissions_for(channel.guild.me)
        pin_perm = getattr(perms, 'pin_messages', 'N/A')
        logger.info(
            f"Bot permissions in #{channel.name}: "
            f"send_messages={perms.send_messages}, "
            f"manage_messages={perms.manage_messages}, "
            f"read_message_history={perms.read_message_history}, "
            f"pin_messages={pin_perm}"
        )

        # Start the update task (on_ready fires again after reconnects)
        if not self.update_conditions.is_running():
            self.update_conditions.start()

    async def on_disconnect(self):
        """Called when bot disconnects"""
        logger.warning("Bot disconnected")

    @tasks.loop(minutes=30)
    async def update_conditions(self):
        """Periodically fetch and update map conditions"""
        try:
            logger.info("Fetching map conditions...")
            events = await self.api.fetch_map_conditions()

            if events is None:
                logger.error("Failed to fetch map conditions")
                return

            await self.post_or_update_current_pin(self.format_current_event_message(events))
            await self.post_schedule_message(self.format_conditions_message(events))

        except Exception as e:
            logger.error(f"Error in update task: {e}", exc_info=True)

    @update_conditions.before_loop
    async def before_update(self):
        """Wait until bot is ready before starting updates"""
        await self.wait_until_ready()

    # ── Formatters ──────────────────────────────────────────────

    def format_current_event_message(self, events: List[Dict]) -> str:
        """Format a compact message showing only the active event for the pinned header."""
        current_time_ms = int(time.time() * 1000)
        active_events = [
            e for e in events
            if e.get('startTime', 0) <= current_time_ms <= e.get('endTime', 0)
        ]

        lines = ["## 🔴 Current Map Condition"]
        if active_events:
            for event in active_events:
                end_time = event.get('endTime', 0) // 1000
                lines.append(
                    f"**{event.get('name', '?')}** on **{event.get('map', '?')}**\n"
                    f"└ Ends: <t:{end_time}:t> (<t:{end_time}:R>)"
                )
        else:
            lines.append("*No active events*")

        lines.append(f"\n*Updated: <t:{int(time.time())}:R>*")
        return "\n".join(lines)

    def format_conditions_message(self, events: List[Dict]) -> str:
        """Format events into a Discord message."""
        current_time_ms = int(time.time() * 1000)

        active_events = [
            e for e in events
            if e.get('startTime', 0) <= current_time_ms <= e.get('endTime', 0)
        ]

        upcoming_events = [
            e for e in events
            if e.get('startTime', 0) > current_time_ms
        ]
        upcoming_events.sort(key=lambda x: x.get('startTime', 0))
        upcoming_events = upcoming_events[:8]

        lines = ["# 🎮 ARC Raiders Map Conditions\n"]

        lines.append("## 🔴 Active Now")
        if active_events:
            for event in active_events:
                condition = event.get('name', '?')
                map_name = event.get('map', '?')
                end_time = event.get('endTime', 0) // 1000

                lines.append(
                    f"**{condition}** on **{map_name}**\n"
                    f"└ Ends: <t:{end_time}:t> (<t:{end_time}:R>)"
                )
        else:
            lines.append("*No active events*")

        lines.append("")

        lines.append("## 📅 Coming Up (Next 8)")
        if upcoming_events:
            for event in upcoming_events:
                condition = event.get('name', '?')
                map_name = event.get('map', '?')
                start_time = event.get('startTime', 0) // 1000

                lines.append(
                    f"**{condition}** on **{map_name}**\n"
                    f"└ Starts: <t:{start_time}:t> (<t:{start_time}:R>)"
                )
        else:
            lines.append("*No upcoming events*")

        lines.append(f"\n*Last updated: <t:{int(time.time())}:R>*")

        return "\n".join(lines)

    def format_trader_message(self, trader_name: str, items: List[Dict]) -> str:
        """Format a trader's inventory into a Discord message."""
        lines = [f"# 🛒 {trader_name}'s Inventory\n"]
        for item in items:
            emoji = RARITY_EMOJI.get(item.get('rarity', ''), '⬜')
            price = f"{item['trader_price']:,}" if item.get('trader_price') else 'N/A'
            lines.append(
                f"{emoji} **{item.get('name', '?')}** — {item.get('rarity', '?')} {item.get('item_type', '')}\n"
                f"└ Price: **{price}** | {item.get('description', '')}"
            )
        return "\n".join(lines)

    def format_search_results(self, query: str, items: List[Dict], total: int) -> str:
        """Format item search results into a Discord message."""
        shown = len(items)
        header = f"# 🔍 Search: *{discord.utils.escape_markdown(query)}*"
        if total == 0:
            return f"{header}\n*No items found.*"

        lines = [header]
        if total > shown:
            lines.append(f"*Showing {shown} of {total} results — try a more specific search.*\n")
        else:
            lines.append(f"*{total} result{'s' if total != 1 else ''} found.*\n")

        for item in items:
            emoji = RARITY_EMOJI.get(item.get('rarity', ''), '⬜')
            meta = ' · '.join(filter(None, [item.get('rarity'), item.get('item_type')]))
            lines.append(f"{emoji} **{item.get('name', '?')}**" + (f" — {meta}" if meta else ''))

            details = []
            if item.get('value'):
                details.append(f"Value: **{item['value']:,}**")
            if item.get('workbench'):
                details.append(f"Crafted at: **{item['workbench']}**")
            if item.get('loot_area'):
                details.append(f"Loot: **{item['loot_area']}**")
            if details:
                lines.append(f"└ {' | '.join(details)}")

            if item.get('description'):
                lines.append(f"  *{item['description']}*")

            components = item.get('components') or []
            if components:
                parts = ', '.join(
                    f"**{c.get('quantity', '?')}x** {c.get('component', {}).get('name', '?')}"
                    for c in components
                )
                lines.append(f"  🔧 Requires: {parts}")

            sold_by = item.get('sold_by') or []
            if sold_by:
                traders = ', '.join(
                    f"{s.get('trader_name', '?')} (**{s.get('price', 0):,}**)"
                    for s in sold_by
                )
                lines.append(f"  🛒 Sold by: {traders}")

        return "\n".join(lines)

    # ── Message management ──────────────────────────────────────

    @staticmethod
    def _split_message(text: str, limit: int = 2000) -> List[str]:
        """Split a message into chunks that fit within Discord's character limit."""
        chunks, current = [], []
        current_len = 0
        for line in text.split('\n'):
            line_len = len(line) + 1  # +1 for the newline we rejoin with
            # Flush current buffer if adding this line would exceed limit
            if current_len + line_len > limit and current:
                chunks.append('\n'.join(current))
                current, current_len = [], 0
            # If a single line itself exceeds the limit, hard-wrap it
            if len(line) >= limit:
                while line:
                    current.append(line[:limit - 1])
                    chunks.append('\n'.join(current))
                    current, current_len = [], 0
                    line = line[limit - 1:]
            else:
                current.append(line)
                current_len += line_len
        if current:
            chunks.append('\n'.join(current))
        return chunks

    async def post_schedule_message(self, content: str):
        """Send or edit the full schedule message (not pinned)."""
        channel = self.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Channel {self.channel_id} not found")
            return

        try:
            if self.schedule_message:
                try:
                    await self.schedule_message.edit(content=content)
                    logger.info("Updated existing schedule message")
                    return
                except discord.NotFound:
                    self.schedule_message = None

            # Recover reference after restart by scanning history
            async for msg in channel.history(limit=50):
                if msg.author == self.user and "ARC Raiders Map Conditions" in msg.content:
                    self.schedule_message = msg
                    await self.schedule_message.edit(content=content)
                    logger.info("Found and updated existing schedule message from history")
                    return

            self.schedule_message = await channel.send(content=content)
            logger.info("Posted new schedule message")

        except discord.Forbidden as e:
            logger.error(f"Missing permissions to post messages — {e}")
        except discord.HTTPException as e:
            logger.error(f"Discord API error: {e}")
        except Exception as e:
            logger.error(f"Error posting schedule message: {e}", exc_info=True)

    async def _ensure_pinned(self, message: discord.Message):
        """Pin a message if it isn't already confirmed pinned."""
        if self.current_pin_verified:
            return
        try:
            pins = {p.id async for p in message.channel.pins()}
            if message.id in pins:
                self.current_pin_verified = True
                return
            await message.pin()
            self.current_pin_verified = True
            logger.info("Pinned current event message")
        except discord.Forbidden as e:
            logger.warning(f"Could not pin current event message — {e}")
        except discord.HTTPException as e:
            logger.warning(f"Failed to pin message (50-pin limit?) — {e}")

    async def post_or_update_current_pin(self, content: str):
        """Post or update the pinned current-event header message."""
        channel = self.get_channel(self.channel_id)
        if not channel:
            return

        try:
            if self.current_pin:
                try:
                    await self.current_pin.edit(content=content)
                    await self._ensure_pinned(self.current_pin)
                    logger.info("Updated current event pin")
                    return
                except discord.NotFound:
                    logger.warning("Current event pin no longer exists, recreating")
                    self.current_pin = None
                    self.current_pin_verified = False

            # Search pinned messages first
            async for pin in channel.pins():
                if pin.author == self.user and "Current Map Condition" in pin.content:
                    self.current_pin = pin
                    self.current_pin_verified = True
                    await self.current_pin.edit(content=content)
                    logger.info("Found and updated existing current event pin")
                    return

            # Fallback: search recent history for an unpinned match
            self.current_pin_verified = False
            async for msg in channel.history(limit=50):
                if msg.author == self.user and "Current Map Condition" in msg.content:
                    self.current_pin = msg
                    await self.current_pin.edit(content=content)
                    await self._ensure_pinned(self.current_pin)
                    logger.info("Found unpinned current event message in history, updated and re-pinned")
                    return

            self.current_pin = await channel.send(content=content)
            logger.info("Posted new current event message")
            await self._ensure_pinned(self.current_pin)

        except discord.Forbidden as e:
            logger.error(f"Missing permissions to post messages — {e}")
        except discord.HTTPException as e:
            logger.error(f"Discord API error: {e}")
        except Exception as e:
            logger.error(f"Error posting/updating current event pin: {e}", exc_info=True)


class ConditionCommands(commands.Cog):
    """User-facing commands."""

    def __init__(self, bot: ConditionBot):
        self.bot = bot

    @commands.command(name='conditions')
    @in_bot_channel()
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def conditions(self, ctx: commands.Context):
        """Show current and upcoming map conditions."""
        events = await self.bot.api.fetch_map_conditions()
        if events is None:
            await ctx.send("Failed to fetch map conditions.")
            return
        await self.bot.post_or_update_current_pin(self.bot.format_current_event_message(events))
        await ctx.send(content=self.bot.format_conditions_message(events))

    @commands.command(name='traders')
    @in_bot_channel()
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def traders(self, ctx: commands.Context, *, name: str):
        """List a trader's inventory. Usage: !traders <name>"""
        traders = await self.bot.api.fetch_traders()
        if traders is None:
            await ctx.send("Failed to fetch trader data.")
            return

        match = next((n for n in traders if n.lower() == name.lower()), None)
        if match is None:
            available = ', '.join(f'`{n}`' for n in sorted(traders.keys()))
            await ctx.send(f"Unknown trader **{discord.utils.escape_markdown(name)}**. Available traders: {available}")
            return

        for chunk in self.bot._split_message(self.bot.format_trader_message(match, traders[match])):
            await ctx.send(content=chunk)

    @commands.command(name='search')
    @in_bot_channel()
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def search(self, ctx: commands.Context, *, query: str):
        """Search for items by name. Usage: !search <item name>"""
        result = await self.bot.api.fetch_items(query)
        if result is None:
            await ctx.send("Failed to fetch item data.")
            return

        items = result.get('data', [])
        total = result.get('pagination', {}).get('total', 0)
        formatted = self.bot.format_search_results(query, items, total)
        for chunk in self.bot._split_message(formatted):
            await ctx.send(content=chunk)

    @conditions.error
    @traders.error
    @search.error
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Command on cooldown — try again in {error.retry_after:.0f}s.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument. Usage: `!{ctx.command.name} <{error.param.name}>`")
        elif isinstance(error, commands.CheckFailure):
            pass  # Silently ignore commands in wrong channel


def main():
    """Main entry point"""
    if not DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not found in environment variables")
        return

    if not DISCORD_CHANNEL_ID:
        logger.error("DISCORD_CHANNEL_ID not found in environment variables")
        return

    intents = discord.Intents.default()
    intents.message_content = True

    bot = ConditionBot(
        command_prefix='!',
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),
        case_insensitive=True,
    )

    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logger.error("Invalid bot token")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)


if __name__ == "__main__":
    main()
