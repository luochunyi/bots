# ARC Raiders Map Condition Discord Bot

A Python Discord bot that automatically posts and updates ARC Raiders map condition schedules to a Discord channel.

## Features

- 🔄 Automatically fetches map conditions from https://arcraiders.com/map-conditions every 15 minutes
- 📌 Posts/updates a pinned message in your Discord channel
- 🔴 Shows currently active events with time remaining
- 📅 Lists the next 8 upcoming events with countdowns
- ⏰ Uses Discord's native timestamp formatting for automatic timezone conversion
- 🛡️ Gracefully handles errors without crashing

## Setup

### 1. Prerequisites

- Python 3.8 or higher
- A Discord bot token (create one at https://discord.com/developers/applications)

### 2. Installation

```bash
# Clone or download this repository
cd condition_bot_python

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   - `DISCORD_BOT_TOKEN`: Your bot token from Discord Developer Portal
   - `DISCORD_CHANNEL_ID`: The ID of the channel where updates should be posted
     - Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
     - Right-click the channel and select "Copy ID"

### 4. Bot Permissions

When inviting the bot to your server, ensure it has these permissions:
- Read Messages/View Channels
- Send Messages
- Manage Messages (for pinning)
- Embed Links
- Read Message History

### 5. Running the Bot

```bash
python bot.py
```

The bot will:
1. Connect to Discord
2. Immediately fetch and post the current conditions
3. Update the message every 15 minutes

## Message Format

The bot posts a message with two sections:

**🔴 Active Now:**
Shows events currently happening with end times

**📅 Coming Up (Next 8):**
Shows the next 8 upcoming events with start times

All timestamps automatically adjust to each user's timezone in Discord.

## Troubleshooting

- **Bot doesn't post**: Check that `DISCORD_CHANNEL_ID` is correct and the bot has permissions
- **Data not updating**: Check logs for fetch errors from arcraiders.com
- **"Invalid token" error**: Verify your `DISCORD_BOT_TOKEN` is correct

## Logs

The bot logs important events and errors to the console. Watch for:
- Successful data fetches
- Message updates
- Any errors or warnings

## License

MIT
