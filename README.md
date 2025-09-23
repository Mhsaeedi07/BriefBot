# BriefBot

A smart Telegram bot that summarizes group conversations, extracts personal action items, and provides AI-powered insights from your chat history.

## Features

### 📊 Conversation Analysis
- **Smart Summaries** - Get AI-powered summaries of group discussions
- **Personal Action Items** - Extract tasks specifically assigned to you
- **Q&A Assistant** - Ask questions about conversation history
- **Context-Aware** - Analyzes from any replied message onwards

### 🎤 Voice to Text
- **Voice Transcription** - Convert voice messages to readable text
- **Multi-language Support** - Transcribes in various languages
- **Easy to Use** - Simply reply to voice messages with `/text`

### 💾 Smart Storage
- **Auto-Archiving** - Automatically archives closed forum topics
- **Message Retention** - Keeps messages for 30 days by default
- **Space Efficient** - Automatic cleanup runs every 24 hours
- **Statistics** - Track storage usage and message counts

### 🔧 Management Commands
- **Reset Data** - Clear all stored messages and start fresh
- **Manual Cleanup** - Remove old messages on demand
- **Storage Stats** - View detailed usage statistics

## Quick Start

### 1. Installation
```bash
git clone https://github.com/yourusername/briefbot.git
cd briefbot
pip install -r requirements.txt
```

### 2. Environment Setup
Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` file with your credentials:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Run the Bot
```bash
python bot.py
```

## Usage Guide

### 📝 Getting Summaries
1. Find any message in a group conversation
2. **Reply to that message**
3. Type `/summary` and send

The bot will analyze all messages from that point onwards and provide a comprehensive summary.

### 🎯 Finding Your Tasks
1. Reply to any message in the conversation
2. Type `/missed` and send

The bot will extract action items specifically assigned to you.

### ❓ Asking Questions
1. Reply to any message
2. Type `/ask your question here`
3. Example: `/ask What deadlines do I have?`

### 🎤 Transcribing Voice Messages
1. Find a voice message (🎙️)
2. **Reply to the voice message**
3. Type `/text` and send

### 📊 Checking Storage
- `/stats` - View storage statistics and usage
- `/cleanup` - Manually remove old messages
- `/reset` - Complete data reset (use with caution!)

## Configuration

### Environment Variables
- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token from @BotFather
- `GEMINI_API_KEY` - Your Google Gemini API key

### Default Settings
- Message retention: 30 days
- Log retention: 5 days
- Auto cleanup: Every 24 hours
- Voice transcription: Enabled

## File Structure

```
briefbot/
├── bot.py              # Main bot application
├── requirements.txt    # Python dependencies
├── .env.example       # Environment template
├── .gitignore         # Git ignore rules
├── chat_storage/      # Message storage (auto-created)
└── logs/             # Error logs (auto-created)
```

## Requirements

- Python 3.8+
- Telegram Bot Token
- Google Gemini API Key
- Internet connection

## How It Works

1. **Message Storage**: BriefBot stores all text messages from groups it's added to
2. **Topic Management**: Automatically creates and manages forum topics
3. **AI Analysis**: Uses Google Gemini to analyze conversations and generate insights
4. **Smart Cleanup**: Automatically removes old messages to manage storage space

## Privacy & Security

- ✅ **Local Storage**: All data is stored locally on your server
- ✅ **No Cloud Dependencies**: Works independently after setup
- ✅ **Auto-Deletion**: Old messages are automatically removed
- ✅ **Error Logging**: Only errors are logged, no personal message content


---

