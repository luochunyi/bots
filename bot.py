#!/usr/bin/env python3
"""
ARC Raiders Map Condition Discord Bot
Fetches and posts map condition schedules to a Discord channel
"""

import os
import re
import json
import time
import asyncio
import logging
from datetime import datetime
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
ARC_RAIDERS_URL = 'https://arcraiders.com/map-conditions'
UPDATE_INTERVAL_MINUTES = 15
BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


class ARCRaidersAPI:
    """Handles fetching and parsing ARC Raiders map condition data"""

    @staticmethod
    def fetch_map_conditions() -> Optional[List[Dict]]:
        """
        Fetch and parse map conditions from ARC Raiders website

        Returns:
            List of event dictionaries or None on error
        """
        try:
            headers = {'User-Agent': BROWSER_USER_AGENT}
            response = requests.get(ARC_RAIDERS_URL, headers=headers, timeout=10)
            response.raise_for_status()

            html_content = response.text
            logger.info("Successfully fetched HTML content")

            # Find script blocks matching self.__next_f.push([1,"...liveEntries..."])
            pattern = r'self\.__next_f\.push\(\[1,"([^"]+)"\]\)'
            matches = re.findall(pattern, html_content)

            for match in matches:
                if 'liveEntries' in match:
                    # Unescape the string
                    unescaped = match.replace(r'\"', '"').replace(r'\\', '\\')

                    # Extract JSON array between "liveEntries": and ,"currentCondition"
                    entries_pattern = r'"liveEntries":\s*(\[.*?\])(?=\s*,\s*"currentCondition")'
                    entries_match = re.search(entries_pattern, unescaped, re.DOTALL)

                    if entries_match:
                        json_str = entries_match.group(1)
                        events = json.loads(json_str)
                        logger.info(f"Successfully parsed {len(events)} events")
                        return events

            logger.error("Could not find liveEntries in HTML content")
            return None

        except requests.RequestException as e:
            logger.error(f"Error fetching data: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None


class ConditionBot(discord.Client):
    """Discord bot for posting ARC Raiders map conditions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_id = DISCORD_CHANNEL_ID
        self.pinned_message: Optional[discord.Message] = None

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f'Logged in as {self.user}')

        # Validate channel
        channel = self.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Could not find channel with ID {self.channel_id}")
            return

        logger.info(f"Using channel: #{channel.name}")

        # Start the update task
        self.update_conditions.start()

    async def on_disconnect(self):
        """Called when bot disconnects"""
        logger.warning("Bot disconnected")

    @tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
    async def update_conditions(self):
        """Periodically fetch and update map conditions"""
        try:
            logger.info("Fetching map conditions...")
            events = ARCRaidersAPI.fetch_map_conditions()

            if events is None:
                logger.error("Failed to fetch map conditions")
                return

            message_content = self.format_conditions_message(events)
            await self.post_or_update_message(message_content)

        except Exception as e:
            logger.error(f"Error in update task: {e}", exc_info=True)

    @update_conditions.before_loop
    async def before_update(self):
        """Wait until bot is ready before starting updates"""
        await self.wait_until_ready()

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
            if e['startTimestamp'] <= current_time_ms <= e['endTimestamp']
        ]

        # Section 2: Upcoming events
        upcoming_events = [
            e for e in events
            if e['startTimestamp'] > current_time_ms
        ]
        upcoming_events.sort(key=lambda x: x['startTimestamp'])
        upcoming_events = upcoming_events[:8]  # Next 8 events

        # Build message
        lines = ["# 🎮 ARC Raiders Map Conditions\n"]

        # Active Now section
        lines.append("## 🔴 Active Now")
        if active_events:
            for event in active_events:
                condition = event['conditionName']
                map_name = event['mapDisplayName']
                end_time = event['endTimestamp'] // 1000  # Convert to seconds

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
                condition = event['conditionName']
                map_name = event['mapDisplayName']
                start_time = event['startTimestamp'] // 1000  # Convert to seconds

                lines.append(
                    f"**{condition}** on **{map_name}**\n"
                    f"└ Starts: <t:{start_time}:t> (<t:{start_time}:R>)"
                )
        else:
            lines.append("*No upcoming events*")

        lines.append(f"\n*Last updated: <t:{int(time.time())}:R>*")

        return "\n".join(lines)

    async def post_or_update_message(self, content: str):
        """
        Post a new message or update the existing pinned message

        Args:
            content: Message content
        """
        channel = self.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Channel {self.channel_id} not found")
            return

        try:
            # Try to update existing pinned message
            if self.pinned_message:
                try:
                    await self.pinned_message.edit(content=content)
                    logger.info("Updated existing message")
                    return
                except discord.NotFound:
                    logger.warning("Pinned message no longer exists, creating new one")
                    self.pinned_message = None

            # Find existing pinned message from this bot
            pins = await channel.pins()
            for pin in pins:
                if pin.author == self.user and "ARC Raiders Map Conditions" in pin.content:
                    self.pinned_message = pin
                    await self.pinned_message.edit(content=content)
                    logger.info("Found and updated existing pinned message")
                    return

            # Create new message and pin it
            self.pinned_message = await channel.send(content=content)
            await self.pinned_message.pin()
            logger.info("Posted and pinned new message")

        except discord.Forbidden:
            logger.error("Missing permissions to post/pin messages")
        except discord.HTTPException as e:
            logger.error(f"Discord API error: {e}")
        except Exception as e:
            logger.error(f"Error posting/updating message: {e}", exc_info=True)


def main():
    """Main entry point"""
    if not DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not found in environment variables")
        return

    if not DISCORD_CHANNEL_ID:
        logger.error("DISCORD_CHANNEL_ID not found in environment variables")
        return

    # Set up intents
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
