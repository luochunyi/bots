#!/usr/bin/env python3
"""
ARC Raiders Map Condition Discord Bot
Fetches and posts map condition schedules to a Discord channel
"""

import os
import time
import logging
from typing import List, Dict, Optional

import discord
from discord.ext import tasks
import requests
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

RARITY_EMOJI = {
    'Common': '⬜',
    'Uncommon': '🟩',
    'Rare': '🟦',
    'Epic': '🟪',
    'Legendary': '🟧',
}


class ARCRaidersAPI:
    """Handles fetching ARC Raiders event schedule data"""

    @staticmethod
    def fetch_map_conditions() -> Optional[List[Dict]]:
        """
        Fetch event schedule from the Metaforge API.

        Returns:
            List of event dictionaries or None on error.
        """
        try:
            response = requests.get(EVENTS_API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            events = data.get('data', [])
            logger.info(f"Successfully fetched {len(events)} events")
            return events
        except requests.RequestException as e:
            logger.error(f"Error fetching data: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None

    @staticmethod
    def fetch_traders() -> Optional[Dict[str, List[Dict]]]:
        """
        Fetch trader inventory data from the Metaforge API.

        Returns:
            Dict mapping trader name -> list of items, or None on error.
        """
        try:
            response = requests.get(TRADERS_API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            traders = data.get('data', {})
            logger.info(f"Successfully fetched traders: {list(traders.keys())}")
            return traders
        except requests.RequestException as e:
            logger.error(f"Error fetching traders: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching traders: {e}")
            return None


class ConditionBot(discord.Client):
    """Discord bot for posting ARC Raiders map conditions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_id = DISCORD_CHANNEL_ID
        self.current_pin: Optional[discord.Message] = None
        self.current_pin_verified: bool = False  # True once we know it's pinned
        self.schedule_message: Optional[discord.Message] = None

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f'Logged in as {self.user}')

        # Validate channel
        channel = self.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Could not find channel with ID {self.channel_id}")
            return

        # Set server nickname
        try:
            await channel.guild.me.edit(nick="SuckBot.69")
            logger.info("Set server nickname to SuckBot.69")
        except discord.Forbidden:
            logger.warning("Missing permissions to change nickname")

        logger.info(f"Using channel: #{channel.name}")

        perms = channel.permissions_for(channel.guild.me)
        pin_perm = getattr(perms, 'pin_messages', 'N/A (update discord.py)')
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
            events = ARCRaidersAPI.fetch_map_conditions()

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

    def format_current_event_message(self, events: List[Dict]) -> str:
        """Format a compact message showing only the active event for the pinned header."""
        current_time_ms = int(time.time() * 1000)
        active_events = [
            e for e in events
            if e['startTime'] <= current_time_ms <= e['endTime']
        ]

        lines = ["## 🔴 Current Map Condition"]
        if active_events:
            for event in active_events:
                end_time = event['endTime'] // 1000
                lines.append(
                    f"**{event['name']}** on **{event['map']}**\n"
                    f"└ Ends: <t:{end_time}:t> (<t:{end_time}:R>)"
                )
        else:
            lines.append("*No active events*")

        lines.append(f"\n*Updated: <t:{int(time.time())}:R>*")
        return "\n".join(lines)

    def format_conditions_message(self, events: List[Dict]) -> str:
        """
        Format events into a Discord message

        Args:
            events: List of event dictionaries

        Returns:
            Formatted message string
        """
        current_time_ms = int(time.time() * 1000)

        # Section 1: Active events
        active_events = [
            e for e in events
            if e['startTime'] <= current_time_ms <= e['endTime']
        ]

        # Section 2: Upcoming events
        upcoming_events = [
            e for e in events
            if e['startTime'] > current_time_ms
        ]
        upcoming_events.sort(key=lambda x: x['startTime'])
        upcoming_events = upcoming_events[:8]  # Next 8 events

        # Build message
        lines = ["# 🎮 ARC Raiders Map Conditions\n"]

        # Active Now section
        lines.append("## 🔴 Active Now")
        if active_events:
            for event in active_events:
                condition = event['name']
                map_name = event['map']
                end_time = event['endTime'] // 1000  # Convert to seconds

                lines.append(
                    f"**{condition}** on **{map_name}**\n"
                    f"└ Ends: <t:{end_time}:t> (<t:{end_time}:R>)"
                )
        else:
            lines.append("*No active events*")

        lines.append("")  # Empty line separator

        # Coming Up section
        lines.append("## 📅 Coming Up (Next 8)")
        if upcoming_events:
            for event in upcoming_events:
                condition = event['name']
                map_name = event['map']
                start_time = event['startTime'] // 1000  # Convert to seconds

                lines.append(
                    f"**{condition}** on **{map_name}**\n"
                    f"└ Starts: <t:{start_time}:t> (<t:{start_time}:R>)"
                )
        else:
            lines.append("*No upcoming events*")

        lines.append(f"\n*Last updated: <t:{int(time.time())}:R>*")

        return "\n".join(lines)

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
                    self.current_pin_verified = True  # found in pins → already pinned
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

    @staticmethod
    def _split_message(text: str, limit: int = 2000) -> List[str]:
        """Split a message into chunks that fit within Discord's character limit."""
        chunks, current = [], []
        current_len = 0
        for line in text.split('\n'):
            # +1 for the newline we'll rejoin with
            if current_len + len(line) + 1 > limit and current:
                chunks.append('\n'.join(current))
                current, current_len = [], 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append('\n'.join(current))
        return chunks

    def format_trader_message(self, trader_name: str, items: List[Dict]) -> str:
        """Format a trader's inventory into a Discord message."""
        lines = [f"# 🛒 {trader_name}'s Inventory\n"]
        for item in items:
            emoji = RARITY_EMOJI.get(item.get('rarity', ''), '⬜')
            price = f"{item['trader_price']:,}" if item.get('trader_price') else 'N/A'
            lines.append(
                f"{emoji} **{item['name']}** — {item.get('rarity', '?')} {item.get('item_type', '')}\n"
                f"└ Price: **{price}** | {item.get('description', '')}"
            )
        return "\n".join(lines)

    async def on_message(self, message: discord.Message):
        """Handle incoming messages for commands."""
        if message.author == self.user:
            return

        content = message.content.strip()

        if content == '!conditions':
            events = ARCRaidersAPI.fetch_map_conditions()
            if events is None:
                await message.channel.send("Failed to fetch map conditions.")
                return
            await self.post_or_update_current_pin(self.format_current_event_message(events))
            await message.channel.send(content=self.format_conditions_message(events))

        elif content.lower().startswith('!traders '):
            traders = ARCRaidersAPI.fetch_traders()
            if traders is None:
                await message.channel.send("Failed to fetch trader data.")
                return

            requested = content[9:].strip()
            # Case-insensitive match against available trader names
            match = next((name for name in traders if name.lower() == requested.lower()), None)
            if match is None:
                available = ', '.join(f'`{n}`' for n in sorted(traders.keys()))
                await message.channel.send(
                    f"Unknown trader **{requested}**. Available traders: {available}"
                )
                return

            for chunk in self._split_message(self.format_trader_message(match, traders[match])):
                await message.channel.send(content=chunk)


def main():
    """Main entry point"""
    if not DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not found in environment variables")
        return

    if not DISCORD_CHANNEL_ID:
        logger.error("DISCORD_CHANNEL_ID not found in environment variables")
        return

    # Set up intents
    # message_content is a privileged intent — enable it at:
    # https://discord.com/developers/applications/ → Bot → Privileged Gateway Intents
    intents = discord.Intents.default()
    intents.message_content = True

    # Create and run bot
    bot = ConditionBot(intents=intents)

    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logger.error("Invalid bot token")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)


if __name__ == "__main__":
    main()
