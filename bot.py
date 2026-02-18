"""Main bot entry point"""
import logging
import time
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import TelegramError

from config import Config
from persistence import init_database
from ticket_manager import TicketManager
from handlers import (
    handle_start_command,
    handle_new_ticket_command,
    handle_status_command,
    handle_user_close_command,
    handle_user_message,
    handle_admin_message,
    handle_close_command,
    handle_callback_query
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Suppress verbose HTTP logs from telegram library
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# Keep our application logs at INFO level
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Initialize bot data after application is created."""
    bot = application.bot
    admin_group_id = int(Config.ADMIN_GROUP_ID)
    
    # Initialize ticket manager
    ticket_manager = TicketManager(bot, admin_group_id)
    application.bot_data['ticket_manager'] = ticket_manager
    
    logger.info("Bot initialized successfully")
    logger.info(f"Admin group ID: {admin_group_id}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors from handlers so one bad update does not stop the bot."""
    logger.error(
        "Exception while handling an update: %s",
        context.error,
        exc_info=context.error,
    )
    if update and getattr(update, "effective_message", None) and context.error:
        try:
            if isinstance(context.error, TelegramError):
                await update.effective_message.reply_text(
                    "🚨 Something went wrong. Please try again in a moment."
                )
        except Exception:
            pass


def main():
    """Main entry point for the bot."""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return
    
    # Initialize database
    try:
        init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return
    
    # Create application with timeouts so long-idle connections don't hang forever
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .get_updates_read_timeout(30.0)
        .get_updates_connect_timeout(10.0)
        .get_updates_write_timeout(10.0)
        .build()
    )
    
    # Register error handler first so handler exceptions don't stop the bot
    application.add_error_handler(error_handler)
    
    # Register handlers
    
    # Handle callback queries (button presses)
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # User commands (private chats)
    application.add_handler(
        CommandHandler("start", handle_start_command, filters=filters.ChatType.PRIVATE)
    )
    application.add_handler(
        CommandHandler("newticket", handle_new_ticket_command, filters=filters.ChatType.PRIVATE)
    )
    application.add_handler(
        CommandHandler("status", handle_status_command, filters=filters.ChatType.PRIVATE)
    )
    application.add_handler(
        CommandHandler("close", handle_user_close_command, filters=filters.ChatType.PRIVATE)
    )
    
    # Handle user messages (private chats with bot)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_user_message
        )
    )
    
    # Admin commands and messages in admin group
    admin_group_id = int(Config.ADMIN_GROUP_ID)
    application.add_handler(
        CommandHandler(
            "close",
            handle_close_command,
            filters=filters.Chat(chat_id=admin_group_id)
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Chat(chat_id=admin_group_id) & ~filters.COMMAND,
            handle_admin_message
        )
    )
    
    # Start the bot with restart loop: if polling exits (e.g. network/API error), reconnect
    logger.info("Starting bot...")
    restart_delay = 5
    while True:
        try:
            application.run_polling(close_loop=False)
            logger.warning("Polling stopped; restarting in %ds...", restart_delay)
        except Exception as e:
            logger.exception("Polling failed: %s; restarting in %ds...", e, restart_delay)
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
