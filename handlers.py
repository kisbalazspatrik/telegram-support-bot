"""Message and command handlers for the Telegram concierge bot."""
import logging
import time
from typing import Dict, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError

from ticket_manager import TicketManager
from persistence import reopen_ticket, resolve_ticket, get_ticket_by_number, _get_db_type

logger = logging.getLogger(__name__)


# Per-user rate limit windows in seconds. Keys are action names used by _rate_limited().
_RATE_LIMIT_WINDOW: Dict[str, float] = {
    "newticket": 30.0,
    "status": 5.0,
    "close": 5.0,
    "message": 1.5,
}
_RATE_LIMIT_MAX_ENTRIES = 10_000
_rate_limit_last: Dict[Tuple[int, str], float] = {}


def _rate_limited(user_id: int, action: str) -> float:
    """Return seconds remaining until the user can perform `action`, or 0.0 if allowed.

    Side effect: when allowed, the call is recorded so subsequent calls within the
    window are blocked.
    """
    window = _RATE_LIMIT_WINDOW.get(action)
    if not window:
        return 0.0
    now = time.monotonic()
    key = (user_id, action)
    last = _rate_limit_last.get(key, 0.0)
    remaining = window - (now - last)
    if remaining > 0:
        return remaining
    # Allow and record. Opportunistically evict if the dict has grown unreasonably.
    if len(_rate_limit_last) >= _RATE_LIMIT_MAX_ENTRIES:
        cutoff = now - max(_RATE_LIMIT_WINDOW.values())
        for k, v in list(_rate_limit_last.items()):
            if v < cutoff:
                del _rate_limit_last[k]
    _rate_limit_last[key] = now
    return 0.0


async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - greet user and show create ticket button."""
    if not update.message or not update.message.from_user:
        return
    
    user = update.message.from_user
    ticket_manager: TicketManager = context.bot_data['ticket_manager']
    
    # Check if user has an open ticket
    existing_ticket = ticket_manager.get_user_ticket(user.id)
    
    if existing_ticket:
        ticket_number = existing_ticket['ticket_number']
        await update.message.reply_text(
            f"Hi! 👋\n\n"
            f"You currently have an open ticket:\n"
            f"🎫 **Ticket #{ticket_number}**\n\n"
            f"Type your message to continue the conversation, or use /status to check your ticket status.",
            parse_mode='Markdown'
        )
    else:
        # Show welcome message with button to create ticket
        keyboard = [
            [InlineKeyboardButton("📝 Create New Ticket", callback_data="create_ticket")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Hi! 👋\n\nHow can we help you today?",
            reply_markup=reply_markup
        )


async def handle_new_ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /newticket command from users."""
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username
    ticket_manager: TicketManager = context.bot_data['ticket_manager']

    wait = _rate_limited(user_id, "newticket")
    if wait > 0:
        await update.message.reply_text(
            f"⏳ Please wait {int(wait) + 1}s before trying again."
        )
        return

    # Check if user already has an open ticket
    existing_ticket = ticket_manager.get_user_ticket(user_id)
    
    if existing_ticket:
        ticket_number = existing_ticket['ticket_number']
        await update.message.reply_text(
            f"You already have an open ticket:\n"
            f"🎫 **Ticket #{ticket_number}**\n\n"
            f"Please close your current ticket first using /close, or continue the conversation.",
            parse_mode='Markdown'
        )
        return
    
    # Prompt user for their issue
    await update.message.reply_text(
        "Please describe your issue or question, and I'll create a ticket for you.\n\n"
        "You can type your message now."
    )


async def handle_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show user's ticket status."""
    if not update.message or not update.message.from_user:
        return
    
    user = update.message.from_user
    user_id = user.id
    ticket_manager: TicketManager = context.bot_data['ticket_manager']

    wait = _rate_limited(user_id, "status")
    if wait > 0:
        await update.message.reply_text(
            f"⏳ Please wait {int(wait) + 1}s before trying again."
        )
        return

    # Get user's most recent ticket (open or closed)
    from persistence import get_db_connection
    
    db_type = _get_db_type()
    placeholder = "%s" if db_type == "POSTGRES" else "?"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT ticket_number, status, created_at, closed_at
            FROM tickets
            WHERE user_id = {placeholder}
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        row = cursor.fetchone()
    
    if row:
        if db_type == "POSTGRES":
            ticket = dict(row)
        else:  # SQLite
            ticket = {
                'ticket_number': row[0],
                'status': row[1],
                'created_at': row[2],
                'closed_at': row[3]
            }
        ticket_number = ticket['ticket_number']
        status = ticket['status']
        
        status_emoji = {
            'open': '🟢',
            'closed': '🔴',
            'resolved': '✅'
        }
        
        status_text = {
            'open': 'Open',
            'closed': 'Closed',
            'resolved': 'Resolved'
        }
        
        emoji = status_emoji.get(status, '⚪')
        status_display = status_text.get(status, status.capitalize())
        
        message = f"{emoji} **🎫 Ticket #{ticket_number}**\n\n"
        message += f"**Status:** {status_display}\n"
        message += f"**Created:** {ticket['created_at']}"
        
        if ticket['closed_at']:
            message += f"\n**Closed:** {ticket['closed_at']}"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "You don't have any tickets yet.\n\n"
            "Use /newticket to create one, or use the button below.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Create New Ticket", callback_data="create_ticket")
            ]])
        )


async def handle_user_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /close command from users."""
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    user_id = user.id
    ticket_manager: TicketManager = context.bot_data['ticket_manager']

    wait = _rate_limited(user_id, "close")
    if wait > 0:
        await update.message.reply_text(
            f"⏳ Please wait {int(wait) + 1}s before trying again."
        )
        return

    # Get user's open ticket
    ticket = ticket_manager.get_user_ticket(user_id)
    
    if not ticket:
        await update.message.reply_text(
            "You don't have an open ticket to close.\n\n"
            "Use /newticket to create one."
        )
        return
    
    ticket_number = ticket['ticket_number']
    
    # Show confirmation with resolve option
    keyboard = [
        [
            InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{ticket_number}"),
            InlineKeyboardButton("❌ Close", callback_data=f"user_close_{ticket_number}")
        ],
        [InlineKeyboardButton("Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Are you sure you want to close **🎫 Ticket #{ticket_number}**?\n\n"
        f"• **✅ Resolve**: Mark as resolved (issue fixed)\n"
        f"• **❌ Close**: Close the ticket\n\n"
        f"Or click 'Cancel' to keep it open.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from users (DMs to the bot)."""
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username
    message_text = update.message.text or ""

    wait = _rate_limited(user_id, "message")
    if wait > 0:
        # Silent-ish rate limit on messages so we don't spam users mid-conversation.
        # Drop the message but warn on the longer waits.
        if wait > 1.0:
            await update.message.reply_text(
                "⏳ You're sending messages too fast. Please slow down a moment."
            )
        return

    ticket_manager: TicketManager = context.bot_data['ticket_manager']

    # Check if user already has an open ticket
    existing_ticket = ticket_manager.get_user_ticket(user_id)
    
    if existing_ticket:
        # User has an open ticket - forward message to admin channel
        ticket_number = existing_ticket['ticket_number']
        channel_id = existing_ticket['channel_id']
        
        try:
            # Forward message to admin channel/topic
            admin_group_id = ticket_manager.admin_group_id
            
            if channel_id != admin_group_id:
                # Send to forum topic
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"@{username if username else user_id}: {message_text}",
                    message_thread_id=channel_id
                )
            else:
                # Fallback: send to group directly
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"@{username if username else user_id}: {message_text}"
                )
        except TelegramError as e:
            logger.error(f"Failed to forward message to admin channel: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't forward your message. Please try again."
            )
    else:
        # User has no open ticket - ask if they want to create one
        # Store the message in user_data so we can use it when they click the button
        context.user_data['pending_message'] = message_text
        
        keyboard = [
            [InlineKeyboardButton("📝 Create New Ticket", callback_data="create_ticket")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👋 It seems like you don't have any ongoing tickets.\n\n"
            "Would you like to create a new ticket?",
            reply_markup=reply_markup
        )


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from admins in the admin group channels."""
    if not update.message or not update.message.chat:
        return
    
    chat_id = update.message.chat.id
    message_text = update.message.text or ""
    
    # Skip if it's a command (handled separately)
    if message_text.startswith('/'):
        return
    
    # Skip if message is empty (could be photo, sticker, etc.)
    if not message_text or not message_text.strip():
        return
    
    ticket_manager: TicketManager = context.bot_data['ticket_manager']
    
    # Get ticket info for this channel
    # For forum topics, we need to check message_thread_id
    channel_id = None
    if update.message.message_thread_id:
        channel_id = update.message.message_thread_id
    else:
        channel_id = chat_id
    
    ticket = ticket_manager.get_ticket_info(channel_id)
    
    if not ticket:
        # Not a ticket channel, ignore
        return
    
    if ticket['status'] in ('closed', 'resolved'):
        # Ticket is closed/resolved, don't relay messages
        return
    
    # Relay message to user
    user_id = ticket['user_id']
    
    try:
        # Relay admin text as plain text. Admins may type stray markdown chars
        # (`*`, `_`, backticks, brackets) that would otherwise cause Telegram to
        # reject the message and silently drop it on the user side.
        await context.bot.send_message(
            chat_id=user_id,
            text=message_text,
        )
    except TelegramError as e:
        error_code = getattr(e, 'message', '')
        logger.error(f"Failed to send message to user {user_id}: {e}")
        
        # Check if user blocked the bot or hasn't started it
        if "blocked" in str(e).lower() or "bot was blocked" in str(e).lower():
            error_msg = "⚠️ Could not deliver message. User has blocked the bot."
        elif "chat not found" in str(e).lower() or "user not found" in str(e).lower():
            error_msg = "⚠️ Could not deliver message. User hasn't started the bot yet."
        else:
            error_msg = f"⚠️ Could not deliver message to user. Error: {str(e)[:50]}"
        
        # Try to notify admin that message couldn't be delivered
        try:
            await update.message.reply_text(error_msg)
        except:
            pass


async def handle_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /close command from admins."""
    if not update.message or not update.message.chat:
        return
    
    chat_id = update.message.chat.id
    
    # Get channel/topic ID
    channel_id = None
    if update.message.message_thread_id:
        channel_id = update.message.message_thread_id
    else:
        channel_id = chat_id
    
    ticket_manager: TicketManager = context.bot_data['ticket_manager']
    
    # Get ticket info
    ticket = ticket_manager.get_ticket_info(channel_id)
    
    if not ticket:
        await update.message.reply_text("This is not a ticket channel.")
        return
    
    if ticket['status'] in ('closed', 'resolved'):
        await update.message.reply_text(f"**🎫 Ticket #{ticket['ticket_number']}** is already closed/resolved.", parse_mode='Markdown')
        return
    
    # Close the ticket
    success = await ticket_manager.close_ticket_channel(ticket['ticket_number'])
    
    if success:
        # Notify user with reopen/resolve options
        user_id = ticket['user_id']
        ticket_number = ticket['ticket_number']
        
        try:
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Reopen", callback_data=f"reopen_{ticket_number}"),
                    InlineKeyboardButton("✅ Resolved", callback_data=f"resolve_{ticket_number}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔴 **Ticket #{ticket_number} has been closed**\n\n"
                     f"If your issue isn't resolved, you can reopen it or mark it as resolved.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except TelegramError as e:
            logger.warning(f"Could not notify user about ticket closure: {e}")
        
        # Confirm to admin
        await update.message.reply_text(f"✅ **Ticket #{ticket_number}** has been closed.", parse_mode='Markdown')
    else:
        await update.message.reply_text("Failed to close ticket. Please try again.")


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline keyboard buttons."""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    data = query.data
    ticket_manager: TicketManager = context.bot_data['ticket_manager']
    
    if data == "create_ticket":
        # User wants to create a ticket
        user = query.from_user
        user_id = user.id
        username = user.username

        wait = _rate_limited(user_id, "newticket")
        if wait > 0:
            await query.edit_message_text(
                f"⏳ Please wait {int(wait) + 1}s before trying again."
            )
            return

        # Check if user already has an open ticket
        existing_ticket = ticket_manager.get_user_ticket(user_id)
        
        if existing_ticket:
            await query.edit_message_text(
                f"You already have an open ticket:\n"
                f"🎫 **Ticket #{existing_ticket['ticket_number']}**\n\n"
                f"Please close your current ticket first using /close, or continue the conversation.",
                parse_mode='Markdown'
            )
        else:
            # Get the pending message from user_data if available
            pending_message = context.user_data.get('pending_message', '')
            
            if pending_message:
                # Create ticket with the stored message
                ticket_info = await ticket_manager.create_ticket_channel(
                    user_id=user_id,
                    username=username,
                    first_message=pending_message
                )
                
                # Clear the pending message
                context.user_data.pop('pending_message', None)
                
                if ticket_info:
                    ticket_number = ticket_info['ticket_number']
                    await query.edit_message_text(
                        f"🎫 **Ticket #{ticket_number} created**\n\n"
                        f"Thank you! Someone will assist you shortly. "
                        f"You can continue the conversation here.\n\n"
                        f"Please tell us your problem in as much detail as possible, "
                        f"including any steps you've taken so far or relevant background. "
                        f"The more information you provide, the quicker we can help you!\n\n"
                        f"Use /status to check your ticket status anytime.",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text(
                        "Sorry, I couldn't create a ticket. Please try again later."
                    )
            else:
                # No pending message, ask them to send one
                await query.edit_message_text(
                    "Great! I'll create a ticket for you.\n\n"
                    "Please describe your issue or question, and I'll create the ticket right away."
                )
    
    elif data.startswith("user_close_"):
        # User confirmed closing their ticket
        try:
            ticket_number = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid ticket number.")
            return
        
        try:
            success = await ticket_manager.close_ticket_channel(ticket_number)
        except Exception as e:
            logger.error(f"Error closing ticket: {e}", exc_info=True)
            await query.edit_message_text(
                "Failed to close ticket. Please try again."
            )
            return
        
        if success:
            await query.edit_message_text(
                f"✅ **Ticket #{ticket_number} has been closed**\n\n"
                f"Use /newticket to create a new ticket if needed.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "Failed to close ticket. It may not exist or is already closed."
            )
    
    elif data.startswith("reopen_"):
        # User wants to reopen a ticket
        try:
            ticket_number = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid ticket number.")
            return
        
        try:
            success = reopen_ticket(ticket_number)
        except Exception as e:
            logger.error(f"Error reopening ticket: {e}", exc_info=True)
            await query.edit_message_text(
                "Failed to reopen ticket. Please try again."
            )
            return
        
        if success:
            # Update channel name back to open status
            ticket = get_ticket_by_number(ticket_number)
            
            if ticket:
                try:
                    channel_name = f"Ticket #{ticket_number} - @{ticket['username']}" if ticket['username'] else f"Ticket #{ticket_number} - {ticket['user_id']}"
                    # Sanitize channel name
                    invalid_chars = ['<', '>', '&', '"', "'"]
                    for char in invalid_chars:
                        channel_name = channel_name.replace(char, '')
                    if len(channel_name) > 128:
                        channel_name = channel_name[:125] + "..."
                    
                    try:
                        await ticket_manager.bot.edit_forum_topic(
                            chat_id=ticket_manager.admin_group_id,
                            message_thread_id=ticket['channel_id'],
                            name=channel_name
                        )
                    except TelegramError as e:
                        logger.warning(f"Could not rename topic: {e}")
                except Exception as e:
                    logger.warning(f"Error updating channel name: {e}")
            
            await query.edit_message_text(
                f"🔄 **Ticket #{ticket_number} has been reopened**\n\n"
                f"You can continue the conversation now.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "Failed to reopen ticket. It may already be open or doesn't exist."
            )
    
    elif data.startswith("resolve_"):
        # User wants to resolve a ticket
        try:
            ticket_number = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid ticket number.")
            return
        
        try:
            success = resolve_ticket(ticket_number)
        except Exception as e:
            logger.error(f"Error resolving ticket: {e}", exc_info=True)
            await query.edit_message_text(
                "Failed to resolve ticket. Please try again."
            )
            return
        
        if success:
            # Update channel name to resolved status
            ticket = get_ticket_by_number(ticket_number)
            
            if ticket:
                try:
                    channel_name = f"RESOLVED #{ticket_number} - @{ticket['username']}" if ticket['username'] else f"RESOLVED #{ticket_number} - {ticket['user_id']}"
                    # Sanitize channel name
                    invalid_chars = ['<', '>', '&', '"', "'"]
                    for char in invalid_chars:
                        channel_name = channel_name.replace(char, '')
                    if len(channel_name) > 128:
                        channel_name = channel_name[:125] + "..."
                    
                    try:
                        await ticket_manager.bot.edit_forum_topic(
                            chat_id=ticket_manager.admin_group_id,
                            message_thread_id=ticket['channel_id'],
                            name=channel_name
                        )
                    except TelegramError as e:
                        logger.warning(f"Could not rename topic: {e}")
                except Exception as e:
                    logger.warning(f"Error updating channel name: {e}")
            
            await query.edit_message_text(
                f"✅ **Ticket #{ticket_number} has been resolved**\n\n"
                f"Thank you for using our support service! 🎉",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "Failed to resolve ticket. It may not exist or is already resolved."
            )
    
    elif data == "cancel":
        await query.edit_message_text("Operation cancelled.")
