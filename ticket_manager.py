"""Ticket management logic for creating and managing support tickets."""
import logging
from typing import Optional, Dict, Any
from telegram import Bot
from telegram.error import TelegramError

from persistence import (
    create_ticket,
    get_ticket_by_channel,
    get_ticket_by_user,
    get_ticket_by_number,
    close_ticket,
    resolve_ticket,
    reopen_ticket,
    get_db_connection
)
from config import Config

logger = logging.getLogger(__name__)


class TicketManager:
    """Manages ticket creation and operations."""
    
    def __init__(self, bot: Bot, admin_group_id: int):
        self.bot = bot
        self.admin_group_id = int(admin_group_id)
    
    async def create_ticket_channel(self, user_id: int, username: Optional[str], 
                                   first_message: str) -> Optional[Dict[str, Any]]:
        """
        Create a new ticket channel in the admin group.
        
        Returns ticket info dict with ticket_number and channel_id, or None on error.
        """
        try:
            # Check if user already has an open ticket
            existing_ticket = get_ticket_by_user(user_id, status='open')
            if existing_ticket:
                logger.info(f"User {user_id} already has open ticket #{existing_ticket['ticket_number']}")
                return existing_ticket
            
            # Generate ticket number and create database record
            ticket_number = create_ticket(user_id, username, 0)  # channel_id will be updated
            
            # Format channel name
            if username:
                channel_name = f"Ticket #{ticket_number} - @{username}"
            else:
                channel_name = f"Ticket #{ticket_number} - {user_id}"
            
            # Sanitize channel name (Telegram has restrictions)
            channel_name = self._sanitize_channel_name(channel_name)
            
            # Create forum topic in admin group (for supergroups with topics enabled)
            channel_id = None
            try:
                topic = await self.bot.create_forum_topic(
                    chat_id=self.admin_group_id,
                    name=channel_name
                )
                channel_id = topic.message_thread_id
                logger.info(f"Created forum topic with thread_id: {channel_id}")
            except TelegramError as e:
                logger.error(f"Failed to create forum topic: {e}")
                # If forum topics aren't available, we'll use the group chat itself
                # In this case, channel_id will be the admin_group_id
                # Note: This is a fallback - ideally the admin group should have forum topics enabled
                channel_id = self.admin_group_id
            
            # Update ticket with actual channel_id
            self._update_ticket_channel(ticket_number, channel_id)
            
            # Send initial message to the channel/topic
            try:
                message_text = f"@{username if username else str(user_id)}: {first_message}"
                
                if channel_id != self.admin_group_id:
                    # Send to forum topic
                    await self.bot.send_message(
                        chat_id=self.admin_group_id,
                        text=message_text,
                        message_thread_id=channel_id
                    )
                else:
                    # Fallback: send to group directly
                    await self.bot.send_message(
                        chat_id=self.admin_group_id,
                        text=message_text
                    )
            except TelegramError as e:
                logger.warning(f"Failed to send initial message: {e}")
            
            ticket_info = {
                'ticket_number': ticket_number,
                'user_id': user_id,
                'username': username,
                'channel_id': channel_id,
                'status': 'open'
            }
            
            logger.info(f"Created ticket #{ticket_number} for user {user_id}")
            return ticket_info
            
        except Exception as e:
            logger.error(f"Error creating ticket: {e}", exc_info=True)
            return None
    
    def _update_ticket_channel(self, ticket_number: int, channel_id: int):
        """Update ticket with actual channel ID."""
        from persistence import _get_db_type
        
        db_type = _get_db_type()
        placeholder = "%s" if db_type == "POSTGRES" else "?"
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE tickets
                SET channel_id = {placeholder}
                WHERE ticket_number = {placeholder}
            """, (channel_id, ticket_number))
            conn.commit()
    
    def _sanitize_channel_name(self, name: str) -> str:
        """Sanitize channel name to meet Telegram requirements."""
        # Telegram channel names have restrictions
        # Remove or replace invalid characters
        invalid_chars = ['<', '>', '&', '"', "'"]
        for char in invalid_chars:
            name = name.replace(char, '')
        # Limit length (Telegram has a max length for channel names)
        if len(name) > 128:
            name = name[:125] + "..."
        return name
    
    def get_ticket_info(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get ticket information by channel ID."""
        return get_ticket_by_channel(channel_id)
    
    def get_ticket_by_number(self, ticket_number: int) -> Optional[Dict[str, Any]]:
        """Get ticket information by ticket number."""
        return get_ticket_by_number(ticket_number)
    
    def get_user_ticket(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get active ticket for a user."""
        return get_ticket_by_user(user_id, status='open')
    
    async def close_ticket_channel(self, ticket_number: int) -> bool:
        """Close a ticket and rename the channel."""
        from persistence import _get_db_type
        
        db_type = _get_db_type()
        placeholder = "%s" if db_type == "POSTGRES" else "?"
        
        ticket = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT ticket_number, user_id, username, channel_id, status
                FROM tickets
                WHERE ticket_number = {placeholder}
            """, (ticket_number,))
            row = cursor.fetchone()
            if row:
                if db_type == "POSTGRES":
                    ticket = dict(row)
                else:  # SQLite
                    ticket = {
                        'ticket_number': row[0],
                        'user_id': row[1],
                        'username': row[2],
                        'channel_id': row[3],
                        'status': row[4]
                    }
        
        if not ticket:
            return False
        
        # Update database
        success = close_ticket(ticket_number)
        
        if success:
            # Rename channel/topic to indicate it's closed
            try:
                if ticket['username']:
                    channel_name = f"CLOSED #{ticket_number} - @{ticket['username']}"
                else:
                    channel_name = f"CLOSED #{ticket_number} - {ticket['user_id']}"
                channel_name = self._sanitize_channel_name(channel_name)
                
                # Try to edit forum topic name
                try:
                    await self.bot.edit_forum_topic(
                        chat_id=self.admin_group_id,
                        message_thread_id=ticket['channel_id'],
                        name=channel_name
                    )
                except TelegramError:
                    # If not a forum topic, we can't rename it
                    logger.info(f"Could not rename topic (may not be a forum topic)")
                
            except Exception as e:
                logger.warning(f"Error renaming channel: {e}")
        
        return success
