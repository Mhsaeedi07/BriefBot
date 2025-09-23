import os
import asyncio
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def setup_logging():
    """Setup logging with file rotation and 5-day retention"""
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Create other necessary directories
    Path("chat_storage").mkdir(exist_ok=True)
    Path("chat_storage/archived_topics").mkdir(exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler (INFO level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (ERROR level only)
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_filename = logs_dir / f"log_{current_date}.log"

    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(logging.ERROR)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Clean up old log files (older than 5 days)
    cleanup_old_logs(logs_dir)

    return logger

def cleanup_old_logs(logs_dir):
    """Remove log files older than 5 days"""
    try:
        cutoff_date = datetime.now() - timedelta(days=5)
        for log_file in logs_dir.glob("log_*.log"):
            try:
                # Extract date from filename (format: log_YYYY-MM-DD.log)
                date_str = log_file.stem[4:]  # Remove "log_" prefix
                file_date = datetime.strptime(date_str, "%Y-%m-%d")

                if file_date < cutoff_date:
                    log_file.unlink()
                    print(f"Removed old log file: {log_file.name}")
            except (ValueError, IndexError):
                # Skip files that don't match expected format
                continue
    except Exception as e:
        print(f"Error cleaning up old logs: {e}")

# Initialize logging
logger = setup_logging()


class GroupAssistantBot:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')

        if not all([self.bot_token, self.gemini_api_key]):
            raise ValueError("Missing required environment variables: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY")

        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

        self.bot_app = Application.builder().token(self.bot_token).build()

        self.storage_dir = Path("chat_storage")
        self.archived_dir = self.storage_dir / "archived_topics"
        self.topics_metadata_file = self.storage_dir / "topics_metadata.json"

        self.topics_metadata = self.load_topics_metadata()
        self.days_to_keep = 30
        self.cleanup_interval = 24 * 60 * 60
        self.is_running = False

        self.setup_handlers()

    def load_topics_metadata(self):
        """Load topics metadata from file"""
        try:
            if self.topics_metadata_file.exists():
                with open(self.topics_metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading topics metadata: {e}")
            return {}

    def save_topics_metadata(self):
        """Save topics metadata to file"""
        try:
            with open(self.topics_metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.topics_metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving topics metadata: {e}")

    def get_topic_key(self, chat_id, topic_id):
        """Generate topic key for metadata"""
        return f"{chat_id}_{topic_id}"

    def setup_handlers(self):
        """Setup command and message handlers"""
        logger.info("Setting up handlers...")
        self.bot_app.handlers = {}

        commands = [
            ("start", self.start_command),
            ("help", self.help_command),
            ("summary", self.summary_command),
            ("missed", self.missed_command),
            ("stats", self.stats_command),
            ("cleanup", self.cleanup_command),
            ("ask", self.ask_command),
            ("reset", self.reset_command),
            ("text", self.text_command),
        ]

        for command, handler in commands:
            self.bot_app.add_handler(CommandHandler(command, handler))

        self.bot_app.add_handler(MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_CREATED,
            self.handle_topic_created
        ))

        self.bot_app.add_handler(MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_CLOSED,
            self.handle_topic_closed
        ))

        self.bot_app.add_handler(MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_REOPENED,
            self.handle_topic_reopened
        ))

        self.bot_app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_text_message
        ), group=1)

        self.bot_app.add_handler(MessageHandler(
            filters.VOICE,
            self.handle_voice_message
        ), group=2)

        self.bot_app.job_queue.run_repeating(
            self.periodic_cleanup,
            interval=self.cleanup_interval,
            first=self.cleanup_interval
        )

        logger.info("All handlers set up successfully")

    def get_storage_filename(self, chat_id, topic_id=None):
        """Generate storage filename for chat/topic"""
        if topic_id:
            return self.storage_dir / f"topic_{chat_id}_{topic_id}.txt"
        else:
            return self.storage_dir / f"chat_{chat_id}.txt"

    def store_message(self, chat_id, topic_id, user_id, username, message_text, message_id=None):
        """Store message in appropriate file"""
        try:
            filename = self.get_storage_filename(chat_id, topic_id)
            filename.parent.mkdir(parents=True, exist_ok=True)

            if topic_id:
                topic_key = self.get_topic_key(chat_id, topic_id)
                if topic_key in self.topics_metadata:
                    self.topics_metadata[topic_key]['message_count'] = self.topics_metadata[topic_key].get('message_count', 0) + 1
                    self.save_topics_metadata()

            timestamp = datetime.now().isoformat()
            line = f"{timestamp}|{user_id}|{username}|{message_id or 'None'}|{message_text}\n"

            with open(filename, 'a', encoding='utf-8') as f:
                f.write(line)

        except Exception as e:
            logger.error(f"Error storing message: {e}")

    def load_messages(self, chat_id, topic_id=None, limit=None, from_message_id=None):
        """Load messages from file"""
        try:
            filename = self.get_storage_filename(chat_id, topic_id)
            if not filename.exists():
                return []

            messages = []
            cutoff_time = datetime.now() - timedelta(days=self.days_to_keep)
            found_start_message = from_message_id is None

            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                try:
                    parts = line.strip().split('|')
                    if len(parts) < 4:
                        continue

                    timestamp_str, user_id, username = parts[0], parts[1], parts[2]

                    if len(parts) == 4:
                        message_id_str, message_text = 'None', parts[3]
                    elif len(parts) >= 5:
                        message_id_str, message_text = parts[3], '|'.join(parts[4:])
                    else:
                        continue

                    msg_time = datetime.fromisoformat(timestamp_str)
                    if msg_time < cutoff_time:
                        continue

                    if from_message_id and not found_start_message:
                        if message_id_str != 'None' and str(message_id_str) == str(from_message_id):
                            found_start_message = True
                        else:
                            continue

                    messages.append({
                        'text': message_text,
                        'user': username,
                        'user_id': int(user_id),
                        'date': msg_time,
                        'formatted_date': msg_time.strftime('%H:%M'),
                        'timestamp': timestamp_str,
                        'message_id': int(message_id_str) if message_id_str != 'None' and message_id_str.isdigit() else None
                    })

                except (ValueError, IndexError):
                    logger.warning(f"Skipping malformed line: {line.strip()}")
                    continue

            messages.sort(key=lambda x: x['date'])
            if limit:
                messages = messages[-limit:]

            return messages

        except Exception as e:
            logger.error(f"Error loading messages: {e}")
            return []

    def cleanup_old_messages(self, chat_id, topic_id=None):
        """Remove messages older than configured days"""
        try:
            filename = self.get_storage_filename(chat_id, topic_id)
            if not filename.exists():
                return 0

            cutoff_time = datetime.now() - timedelta(days=self.days_to_keep)
            kept_lines = []
            removed_count = 0

            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                try:
                    parts = line.strip().split('|', 4)
                    if len(parts) < 4:
                        kept_lines.append(line)
                        continue

                    timestamp_str = parts[0]
                    msg_time = datetime.fromisoformat(timestamp_str)

                    if msg_time >= cutoff_time:
                        kept_lines.append(line)
                    else:
                        removed_count += 1

                except (ValueError, IndexError):
                    kept_lines.append(line)

            with open(filename, 'w', encoding='utf-8') as f:
                f.writelines(kept_lines)

            return removed_count

        except Exception as e:
            logger.error(f"Error cleaning up messages: {e}")
            return 0

    async def handle_topic_created(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle forum topic creation"""
        try:
            chat_id = update.effective_chat.id
            topic_id = update.message.message_thread_id
            topic_name = update.message.forum_topic_created.name

            logger.info(f"New topic created: {topic_name} (ID: {topic_id}) in chat {chat_id}")

            topic_key = self.get_topic_key(chat_id, topic_id)
            self.topics_metadata[topic_key] = {
                'topic_id': topic_id,
                'chat_id': chat_id,
                'name': topic_name,
                'status': 'open',
                'created_at': datetime.now().isoformat(),
                'closed_at': None,
                'message_count': 0
            }

            filename = self.get_storage_filename(chat_id, topic_id)
            filename.touch()
            self.save_topics_metadata()

        except Exception as e:
            logger.error(f"Error handling topic creation: {e}")

    async def handle_topic_closed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle forum topic closure"""
        try:
            chat_id = update.effective_chat.id
            topic_id = update.message.message_thread_id

            logger.info(f"Topic closed: {topic_id} in chat {chat_id}")

            topic_key = self.get_topic_key(chat_id, topic_id)
            if topic_key in self.topics_metadata:
                self.topics_metadata[topic_key]['status'] = 'closed'
                self.topics_metadata[topic_key]['closed_at'] = datetime.now().isoformat()

                current_file = self.get_storage_filename(chat_id, topic_id)
                if current_file.exists():
                    archived_file = self.archived_dir / current_file.name
                    current_file.rename(archived_file)

            self.save_topics_metadata()

        except Exception as e:
            logger.error(f"Error handling topic closure: {e}")

    async def handle_topic_reopened(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle forum topic reopening"""
        try:
            chat_id = update.effective_chat.id
            topic_id = update.message.message_thread_id

            logger.info(f"Topic reopened: {topic_id} in chat {chat_id}")

            topic_key = self.get_topic_key(chat_id, topic_id)
            if topic_key in self.topics_metadata:
                self.topics_metadata[topic_key]['status'] = 'open'
                self.topics_metadata[topic_key]['closed_at'] = None

                archived_file = self.archived_dir / f"topic_{chat_id}_{topic_id}.txt"
                current_file = self.get_storage_filename(chat_id, topic_id)

                if archived_file.exists():
                    archived_file.rename(current_file)
                else:
                    current_file.touch()

            self.save_topics_metadata()

        except Exception as e:
            logger.error(f"Error handling topic reopening: {e}")

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle and store text messages"""
        try:
            if not update.message or not update.message.text:
                return

            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)

            if not topic_id and update.effective_chat.is_forum:
                topic_id = 1
                filename = self.get_storage_filename(chat_id, topic_id)
                filename.parent.mkdir(parents=True, exist_ok=True)
                if not filename.exists():
                    filename.touch()
                    topic_key = self.get_topic_key(chat_id, topic_id)
                    if topic_key not in self.topics_metadata:
                        self.topics_metadata[topic_key] = {
                            'topic_id': topic_id,
                            'chat_id': chat_id,
                            'name': 'General',
                            'status': 'open',
                            'created_at': datetime.now().isoformat(),
                            'closed_at': None,
                            'message_count': 0
                        }
                        self.save_topics_metadata()

            if update.message.from_user:
                user_id = update.message.from_user.id
                username = update.message.from_user.username or update.message.from_user.first_name or "Unknown"
            else:
                user_id = "bot"
                username = "Bot"

            message_text = update.message.text
            message_id = update.message.message_id

            self.store_message(chat_id, topic_id, user_id, username, message_text, message_id)

        except Exception as e:
            logger.error(f"Error handling text message: {e}")

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages - log but don't store"""
        try:
            if not update.message or not update.message.voice:
                return

            voice = update.message.voice
            logger.info(f"Received voice message: duration={voice.duration}s, file_id={voice.file_id}")

        except Exception as e:
            logger.error(f"Error handling voice message: {e}")

    async def text_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /text command - convert voice message to text"""
        try:
            if not update.message:
                logger.warning("Received update without message in text_command")
                return

            if not update.message.reply_to_message:
                await update.message.reply_text("""
⚠️ **VOICE MESSAGE REQUIRED**

❌ **Error:** You need to reply to a voice message!

🎤 **How to use:**
   1. Find a voice message (🎙️)
   2. Reply to that voice message
   3. Type `/text` and send

💡 **Tip:** I can transcribe voice messages in multiple languages!
                """)
                return

            if not update.message.reply_to_message.voice:
                await update.message.reply_text("Please reply to a voice message to convert it to text.")
                return

            voice = update.message.reply_to_message.voice
            await update.message.reply_text("🔄 Processing voice message, please wait...")

            voice_file = await voice.get_file()
            voice_bytes = await voice_file.download_as_bytearray()

            transcribed_text = await self.convert_voice_to_text(voice_bytes)

            if transcribed_text:
                response = f"""
🎤 **VOICE MESSAGE TRANSCRIBED**

🎙️ **Voice Duration:** {voice.duration} seconds

{transcribed_text}

💡 **Tip:** You can ask questions about this transcription using `/ask`!
                """
                try:
                    await update.message.reply_text(response, parse_mode='Markdown')
                except Exception:
                    plain_response = response.replace('**', '').replace('*', '').replace('`', '').replace('┏', '═').replace('┃', '│').replace('┗', '═').replace('┓', '═').replace('└', '═').replace('┐', '═')
                    await update.message.reply_text(plain_response)
            else:
                await update.message.reply_text("Sorry, I couldn't transcribe the voice message. Please try again or check the audio quality.")

        except Exception as e:
            logger.error(f"Error in text_command: {e}")
            if update.message:
                await update.message.reply_text("Sorry, I couldn't process the voice message right now.")

    async def convert_voice_to_text(self, voice_bytes):
        """Convert voice message bytes to text using Gemini AI"""
        try:
            prompt = """
            Please transcribe the speech from this audio file.
            The audio is a voice message from a messaging app.

            Return only the transcribed text without any additional commentary.
            If you cannot understand the audio clearly, please respond with "Audio unclear, could not transcribe."
            """

            audio_data = {
                "mime_type": "audio/ogg",
                "data": bytes(voice_bytes)
            }

            response = await asyncio.to_thread(
                self.model.generate_content,
                [prompt, audio_data]
            )

            return response.text.strip()

        except Exception as e:
            logger.error(f"Error converting voice to text: {e}")
            return None

    async def start_clients(self):
        """Start Bot API client"""
        try:
            logger.info("Starting Bot API...")
            await self.bot_app.initialize()
            await self.bot_app.start()
            logger.info("Bot API started successfully!")
            self.is_running = True
        except Exception as e:
            logger.error(f"Error starting client: {e}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_msg = """
🤖 **Welcome to Group Assistant Bot!**

📚 **MAIN FEATURES:**

📊 **Conversation Analysis** (Reply to any message):
   └─ • `/summary` 📝 - Get AI-powered conversation summary
   └─ • `/missed` 🎯 - Extract your personal action items & tasks
   └─ • `/ask <question>` ❓ - Ask AI questions about the conversation

🎤 **Voice to Text** (Reply to voice messages):
   └─ • `/text` 🎙️ - Convert voice messages to readable text

📈 **Storage Management**:
   └─ • `/stats` 📊 - View detailed storage statistics
   └─ • `/cleanup` 🧹 - Manually clean old messages
   └─ • `/reset` 🗑️ - Complete data reset (use with caution!)

⚙️ **BOT SETTINGS:**
   └─ 📅 Message retention: 30 days
   └─ 💾 Storage: File-based system

💡 **TIP:** Most analysis commands work best when you reply to a specific message!

Use `/help` for detailed usage examples.
        """
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_msg = """
📖 **COMMAND GUIDE**

🔧 **HOW TO USE EACH COMMAND**

📊 **ANALYSIS COMMANDS** (Reply to any message):

📝 `/summary`
   • Creates AI summary of conversation from replied message
   • Great for catching up on long discussions
   • Highlights key decisions, tasks, and important points

🎯 `/missed`
   • Extracts YOUR personal action items & tasks
   • Shows only items specifically assigned to you
   • Perfect for catching up on what you need to do

❓ `/ask <question>`
   • Ask AI questions about the conversation
   • Get answers based on chat history
   • Example: `/ask What deadlines do I have?`

🎤 **VOICE COMMANDS** (Reply to voice messages):

🎙️ `/text`
   • Converts voice messages to text
   • Great for accessibility and quick reference

📈 **MANAGEMENT COMMANDS:**

   📊 `/stats` - View detailed storage and usage statistics
   🧹 `/cleanup` - Manually clean old messages (older than 30 days)
   🗑️ `/reset` - Complete data reset (use with extreme caution!)

💡 **QUICK EXAMPLES:**
   • Reply to a message + `/summary`
   • Reply to a message + `/missed`
   • Reply to a message + `/ask What are my tasks?`
   • Reply to voice message + `/text`

🎯 **PRO TIP:** All analysis commands work best when you reply to the message where the topic started!
        """
        await update.message.reply_text(help_msg, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show storage statistics"""
        try:
            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)

            if topic_id:
                filename = self.get_storage_filename(chat_id, topic_id)
                topic_key = self.get_topic_key(chat_id, topic_id)

                if not filename.exists():
                    await update.message.reply_text("No messages stored for this topic yet.")
                    return

                topic_info = self.topics_metadata.get(topic_key, {})
                topic_name = topic_info.get('name', 'Unknown')
                topic_status = topic_info.get('status', 'unknown')

                with open(filename, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                message_count = len(lines)
                file_size = filename.stat().st_size
                file_size_mb = file_size / 1024 / 1024

                stats_msg = f"""
📊 **TOPIC STATISTICS**

📁 **Topic Name:** {topic_name}
📊 **Status:** {topic_status.upper()}
💬 **Messages Stored:** {message_count:,}
💾 **File Size:** {file_size_mb:.2f} MB
📅 **Retention Period:** {self.days_to_keep} days
📈 **Storage Efficiency:** {(message_count / max(file_size_mb, 0.001)):.0f} messages/MB
                """
            else:
                stats_msg = "📊 **Chat Statistics:**\n\n"
                total_topics = 0
                total_messages = 0
                total_size = 0

                for topic_key, topic_info in self.topics_metadata.items():
                    if topic_info['chat_id'] == chat_id:
                        total_topics += 1
                        total_messages += topic_info.get('message_count', 0)

                        filename = self.get_storage_filename(chat_id, topic_info['topic_id'])
                        if filename.exists():
                            total_size += filename.stat().st_size

                total_size_mb = total_size / 1024 / 1024

                stats_msg += f"""
📁 **Total Topics:** {total_topics}
💬 **Total Messages:** {total_messages:,}
💾 **Total Storage:** {total_size_mb:.2f} MB
📅 **Retention Period:** {self.days_to_keep} days
📈 **Storage Efficiency:** {(total_messages / max(total_size_mb, 0.001)):.0f} messages/MB

🧹 **Auto Cleanup:** Enabled (runs every 24 hours)
🤖 **AI Features:** Analysis & voice transcription
                """

            try:
                await update.message.reply_text(stats_msg, parse_mode='Markdown')
            except Exception:
                plain_stats = stats_msg.replace('**', '').replace('*', '').replace('`', '')
                await update.message.reply_text(plain_stats)

        except Exception as e:
            logger.error(f"Error in stats_command: {e}")
            await update.message.reply_text("Error retrieving statistics.")

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Complete reset - delete all stored messages and data"""
        try:
            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)

            if topic_id:
                filename = self.get_storage_filename(chat_id, topic_id)
                topic_key = self.get_topic_key(chat_id, topic_id)

                if filename.exists():
                    filename.unlink()

                archived_file = self.archived_dir / filename.name
                if archived_file.exists():
                    archived_file.unlink()

                if topic_key in self.topics_metadata:
                    del self.topics_metadata[topic_key]
                    self.save_topics_metadata()

                await update.message.reply_text(f"""
🗑️ **RESET COMPLETED**

✅ **Topic ID:** {topic_id}
🗑️ **Action:** All data permanently deleted
🔄 **Archived files:** Also removed if existed

💡 **Note:** This action cannot be undone. New messages will start fresh storage.
                """)
            else:
                files_deleted = 0

                for filepath in self.storage_dir.glob(f"topic_{chat_id}_*.txt"):
                    filepath.unlink()
                    files_deleted += 1

                for filepath in self.archived_dir.glob(f"topic_{chat_id}_*.txt"):
                    filepath.unlink()
                    files_deleted += 1

                chat_file = self.get_storage_filename(chat_id, None)
                if chat_file.exists():
                    chat_file.unlink()
                    files_deleted += 1

                keys_to_remove = [key for key, data in self.topics_metadata.items() if data.get('chat_id') == chat_id]
                for key in keys_to_remove:
                    del self.topics_metadata[key]

                if keys_to_remove:
                    self.save_topics_metadata()

                await update.message.reply_text(f"""
🗑️ **COMPLETE RESET COMPLETED**

📁 **Files Deleted:** {files_deleted}
🗑️ **Topics Cleared:** All topics for this chat
💾 **Metadata:** Reset completely
🔄 **Fresh Start:** Ready for new messages

⚠️ **Warning:** This action cannot be undone. All historical data is permanently removed.
                """)

        except Exception as e:
            logger.error(f"Error in reset_command: {e}")
            await update.message.reply_text("Error during reset operation.")

    async def cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manual cleanup of old messages"""
        try:
            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)

            removed_count = self.cleanup_old_messages(chat_id, topic_id)

            await update.message.reply_text(f"""
🧹 **CLEANUP COMPLETED**

🗑️ **Messages Removed:** {removed_count}
📅 **Age:** Older than {self.days_to_keep} days
💾 **Storage:** Optimized and cleaned

💡 **Tip:** Automatic cleanup runs every 24 hours to keep storage efficient.
                """)

        except Exception as e:
            logger.error(f"Error in cleanup_command: {e}")
            await update.message.reply_text("Error during cleanup.")

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /summary command - requires reply to message"""
        try:
            if not update.message:
                logger.warning("Received update without message in summary_command")
                return

            if not update.message.reply_to_message:
                await update.message.reply_text("""
⚠️ **REPLY REQUIRED**

❌ **Error:** You need to reply to a message first!

📝 **How to use:**
   1. Find the message you want to summarize from
   2. Reply to that message
   3. Type `/summary` and send

💡 **Tip:** The summary will include all messages from the replied message onwards!
                """)
                return

            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)
            from_message_id = update.message.reply_to_message.message_id

            messages = self.load_messages(chat_id, topic_id, from_message_id=from_message_id)

            if not messages:
                await update.message.reply_text("No messages found to summarize from that point onwards")
                return

            logger.info(f"Found {len(messages)} messages for summary")
            summary = await self.generate_summary(messages)

            message_text = f"""
📊 **CONVERSATION SUMMARY**

📈 **Analyzed:** {len(messages)} messages from replied message onwards

{summary}

💡 **Tip:** Use `/missed` to find your personal action items from these messages!
            """

            try:
                await update.message.reply_text(message_text, parse_mode='Markdown')
            except Exception:
                plain_text = message_text.replace('**', '').replace('*', '').replace('`', '').replace('┏', '═').replace('┃', '│').replace('┗', '═').replace('┓', '═').replace('└', '═').replace('┐', '═')
                await update.message.reply_text(plain_text)

        except Exception as e:
            logger.error(f"Error in summary_command: {e}")
            if update.message:
                await update.message.reply_text("Sorry, I couldn't generate a summary right now")

    async def missed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /missed command - requires reply to message"""
        try:
            if not update.message:
                logger.warning("Received update without message in missed_command")
                return

            if not update.message.reply_to_message:
                await update.message.reply_text("Please reply to a message and then use /missed to get action items from that point onwards.")
                return

            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)
            from_message_id = update.message.reply_to_message.message_id

            messages = self.load_messages(chat_id, topic_id, from_message_id=from_message_id)

            if not messages:
                await update.message.reply_text("No messages found to analyze from that point onwards.")
                return

            logger.info(f"Found {len(messages)} messages for missed items analysis")
            user_name = update.effective_user.first_name or update.effective_user.username or "you"
            action_items = await self.extract_action_items(messages, user_name)

            message_text = f"""
🎯 **PERSONAL ACTION ITEMS FOR {user_name.upper()}**

📈 **Analyzed:** {len(messages)} messages from replied message onwards

{action_items}

💡 **Tip:** Use `/ask` if you have questions about these action items!
            """

            try:
                await update.message.reply_text(message_text, parse_mode='Markdown')
            except Exception:
                plain_text = message_text.replace('**', '').replace('*', '').replace('`', '').replace('┏', '═').replace('┃', '│').replace('┗', '═').replace('┓', '═').replace('└', '═').replace('┐', '═')
                await update.message.reply_text(plain_text)

        except Exception as e:
            logger.error(f"Error in missed_command: {e}")
            if update.message:
                await update.message.reply_text("Sorry, I couldn't analyze missed items right now")

    async def ask_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ask command for questions - requires reply to message"""
        try:
            if not update.message:
                logger.warning("Received update without message in ask_command")
                return

            if not update.message.reply_to_message:
                await update.message.reply_text("Please reply to a message and then use /ask to ask a question based on messages from that point onwards.")
                return

            if not context.args:
                await update.message.reply_text(
                    "Please provide your question after the /ask command.\n"
                    "Example: Reply to a message + `/ask What are my tasks?`"
                )
                return

            question = " ".join(context.args)
            chat_id = update.effective_chat.id
            topic_id = getattr(update.message, 'message_thread_id', None)
            from_message_id = update.message.reply_to_message.message_id

            messages = self.load_messages(chat_id, topic_id, from_message_id=from_message_id)

            if not messages:
                await update.message.reply_text("No messages found to analyze from that point onwards.")
                return

            answer = await self.answer_question(question, messages, update.effective_user.first_name)
            response = f"""
❓ **AI Q&A RESPONSE**

🤔 **Your Question:** {question}
📊 **Analyzed:** {len(messages)} messages from replied message

{answer}

💡 **Tip:** Use `/summary` for a complete overview of these messages!
            """

            try:
                await update.message.reply_text(response, parse_mode='Markdown')
            except Exception:
                plain_response = response.replace('**', '').replace('*', '').replace('`', '').replace('┏', '═').replace('┃', '│').replace('┗', '═').replace('┓', '═').replace('└', '═').replace('┐', '═')
                await update.message.reply_text(plain_response)

        except Exception as e:
            logger.error(f"Error in ask_command: {e}")
            if update.message:
                await update.message.reply_text("Sorry, I couldn't process your question right now.")

    async def generate_summary(self, messages):
        """Generate conversation summary using Gemini AI"""
        try:
            if not messages:
                return "No messages to summarize"

            conversation = "\n".join([f"{msg['user']} ({msg['formatted_date']}): {msg['text']}" for msg in messages])

            prompt = f"""
            Summarize the following group conversation. Focus on:
            - Key decisions made
            - Tasks assigned or mentioned
            - Important discussions
            - Deadlines or time-sensitive items

            Conversation:
            {conversation}

            Provide a clear, organized summary in English:
            """

            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Sorry, I couldn't generate a summary"

    async def extract_action_items(self, messages, user_name):
        """Extract action items for specific user using Gemini AI"""
        try:
            if not messages:
                return "No messages to analyze"

            conversation = "\n".join([f"{msg['user']} ({msg['formatted_date']}): {msg['text']}" for msg in messages])

            prompt = f"""
            Analyze this conversation and extract ONLY action items that are specifically for "{user_name}".

            Look for things that {user_name} personally needs to do:
            - Tasks directly assigned to {user_name} by name
            - Messages that mention "@{user_name}" or "@{user_name.lower()}"
            - Questions specifically directed at {user_name}
            - Requests made specifically to {user_name}
            - When someone says "{user_name}, please..." or "Hey {user_name}..."
            - Deadlines that {user_name} personally needs to meet
            - Things {user_name} needs to respond to or follow up on
            - Any message containing "{user_name}" as a direct reference or mention

            DO NOT include:
            - General group announcements
            - Tasks assigned to other people
            - Questions asked to the group in general (unless {user_name} is specifically mentioned)

            Conversation:
            {conversation}

            Format response as:
            • [Specific action item for {user_name}]

            If no specific personal action items found for {user_name}, return "No personal action items found for you in these messages."
            Respond in English only.
            """

            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text

        except Exception as e:
            logger.error(f"Error extracting action items: {e}")
            return "Sorry, I couldn't extract action items"

    async def answer_question(self, question, messages, user_name):
        """Answer user question based on conversation context using Gemini AI"""
        try:
            conversation = "\n".join([f"{msg['user']} ({msg['formatted_date']}): {msg['text']}" for msg in messages])

            prompt = f"""
            Based on this group conversation, answer the following question from {user_name}:

            Question: {question}

            Conversation context:
            {conversation}

            Provide a helpful answer based on the conversation. If the information isn't available in the conversation, say so clearly.
            Respond in English only.
            """

            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text

        except Exception as e:
            logger.error(f"Error answering question: {e}")
            return "Sorry, I couldn't process your question"

    async def periodic_cleanup(self, context: ContextTypes.DEFAULT_TYPE):
        """Periodic cleanup of old messages"""
        try:
            logger.info("Running periodic cleanup...")
            total_cleaned = 0

            for filepath in self.storage_dir.glob("*.txt"):
                try:
                    filename = filepath.name
                    if filename.startswith("topic_"):
                        parts = filename[6:-4].split("_", 2)
                        if len(parts) >= 2:
                            chat_id = int(parts[0])
                            topic_id = int(parts[1])
                            cleaned = self.cleanup_old_messages(chat_id, topic_id)
                            total_cleaned += cleaned
                    elif filename.startswith("chat_"):
                        chat_id = int(filename[5:-4])
                        cleaned = self.cleanup_old_messages(chat_id)
                        total_cleaned += cleaned

                except (ValueError, IndexError) as e:
                    logger.warning(f"Skipping cleanup for file {filepath}: {e}")
                    continue

            self.save_topics_metadata()
            logger.info(f"Periodic cleanup completed. Removed {total_cleaned} old messages.")

        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.is_running = False

        try:
            import signal
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        except ImportError:
            pass

    async def run(self):
        """Run the bot"""
        try:
            await self.start_clients()
            logger.info("Bot is running...")

            await self.bot_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Bot polling started...")

            while self.is_running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error running bot: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Stop bot gracefully"""
        logger.info("Stopping bot...")
        self.is_running = False

        try:
            self.save_topics_metadata()

            if hasattr(self.bot_app, 'updater') and self.bot_app.updater and self.bot_app.updater.running:
                await self.bot_app.updater.stop()

            if self.bot_app.running:
                await self.bot_app.stop()

            await self.bot_app.shutdown()
            logger.info("Bot stopped successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def main():
    """Main function to run the bot"""
    bot = GroupAssistantBot()
    bot.setup_signal_handlers()

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        bot.is_running = False
    except Exception as e:
        logger.error(f"Bot error: {e}")
        bot.is_running = False
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())