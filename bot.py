#!/usr/bin/env python3
"""
ARC Raiders Map Condition Discord Bot
Fetches and posts map condition schedules to a Discord channel
"""

import os
import time
import logging
from datetime import time as dt_time
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

# Fire at every XX:00 and XX:30 UTC
UPDATE_TIMES = [dt_time(hour=h, minute=m) for h in range(24) for m in (0, 30)]


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

    @tasks.loop(time=UPDATE_TIMES)
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
            pins = await message.channel.pins()
            if message.id in {p.id for p in pins}:
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
            for pin in await channel.pins():
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

    async def on_message(self, message: discord.Message):
        """Handle incoming messages for commands."""
        if message.author == self.user:
            return
        if message.content.strip() == '!conditions':
            events = ARCRaidersAPI.fetch_map_conditions()
            if events is None:
                await message.channel.send("Failed to fetch map conditions.")
                return
            await self.post_or_update_current_pin(self.format_current_event_message(events))
            await message.channel.send(content=self.format_conditions_message(events))


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
