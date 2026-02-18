# Telegram Support Bot

A Telegram bot that creates a ticketing system for customer support. Users can DM the bot to create tickets, and admins can respond in dedicated channels within an admin group.

## Features

- **Ticket Creation**: Users can create tickets via `/start`, `/newticket`, or by sending a message
- **Interactive Buttons**: Welcome message with inline keyboard for easy ticket creation
- **Channel Management**: Each ticket gets its own channel/topic in the admin group
- **Message Relay**: Messages are relayed bidirectionally between users and admins
- **Ticket Management**: 
  - Admins can close tickets with `/close` command
  - Users can check status with `/status`
  - Users can close their own tickets with `/close`
  - Reopen closed tickets
  - Mark tickets as resolved
- **Database Support**: Choose between SQLite (LOCAL) or PostgreSQL (Supabase, etc.)
- **Persistence**: Database ensures ticket numbers persist across restarts
- **No Duplicate Tickets**: Users can only have one open ticket at a time

## Prerequisites

- Python 3.8 or higher
- A Telegram bot token (get one from [@BotFather](https://t.me/botfather))
- A Telegram supergroup with forum topics enabled (for admin group)
- Admin permissions for the bot in the admin group
- (Optional) PostgreSQL database if using `DB_TYPE=POSTGRES`

## Installation

1. Clone the repository:
```bash
git clone <https://github.com/kisbalazspatrik/telegram-support-bot>
cd telegram-support-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file from the example:
```bash
cp .env.example .env
```

4. Edit `.env` and add your credentials:
```env
BOT_TOKEN=your_bot_token_here
ADMIN_GROUP_ID=your_admin_group_id_here
DB_TYPE=LOCAL  # or POSTGRES for PostgreSQL/Supabase
# DATABASE_URL is only required if DB_TYPE=POSTGRES
```

## Configuration

### Environment Variables

- `BOT_TOKEN` (required): Your Telegram bot token from BotFather
- `ADMIN_GROUP_ID` (required): The ID of your admin group (negative integer)
- `DB_TYPE` (optional): Database type - `LOCAL` (SQLite) or `POSTGRES` (PostgreSQL). Defaults to `LOCAL`
- `DATABASE_URL` (required if `DB_TYPE=POSTGRES`): PostgreSQL connection string

### Getting Your Admin Group ID

1. Add [@userinfobot](https://t.me/userinfobot) to your admin group
2. The bot will send the group ID (it's a negative number like `-1001234567890`)
3. Copy this ID to your `.env` file

### Enabling Forum Topics

Your admin group must be a supergroup with forum topics enabled:

1. Go to your admin group settings
2. Enable "Topics" (this converts it to a forum)
3. Make sure your bot has admin permissions

### Database Configuration

#### SQLite (LOCAL) - Default

No additional setup required. The bot will create a `tickets.db` file automatically.

#### PostgreSQL (POSTGRES)

1. Set `DB_TYPE=POSTGRES` in your `.env` file

2. Add your database connection string:
```env
DATABASE_URL=postgresql://user:password@host:port/database
```

For Supabase:
- Go to your project settings → Database → Connection string
- Copy the connection string and add it to `.env`

## Usage

### Running the Bot

```bash
python bot.py
```

The bot will:
- Initialize the database on first run
- Start listening for messages
- Create tickets when users DM it

### User Commands

- `/start` - Welcome message with button to create a ticket
- `/newticket` - Create a new support ticket
- `/status` - Check your current ticket status
- `/close` - Close your current ticket (with resolve option)

### User Flow

1. User sends `/start` to the bot
2. Bot responds with: `"Hi! 👋 How can we help you today?"` and a "Create New Ticket" button
3. User clicks button or sends a message
4. Bot responds: `"Ticket #1 created. Someone will assist you shortly."`
5. A new channel/topic is created in the admin group: `Ticket #1 - @username`
6. User's message appears in the admin channel
7. User can continue messaging - all messages are relayed to admins
8. When ticket is closed, user gets options to reopen or mark as resolved

### Admin Flow

1. Admin sees new channel `Ticket #1 - @username` in admin group
2. Admin responds in the channel
3. User receives the response directly (no prefix)
4. Admin types `/close` to close the ticket
5. Channel is renamed to `CLOSED #1 - @username`
6. User is notified with buttons to reopen or mark as resolved

## Database

The bot supports two database backends:

### SQLite (LOCAL)
- Database file: `tickets.db` (created automatically)
- Stores ticket counter, ticket information, and timestamps
- Perfect for small to medium deployments
- No additional setup required

### PostgreSQL (POSTGRES)
- Requires a PostgreSQL database (e.g., Supabase)
- Better for production deployments with multiple instances
- Supports connection pooling
- Requires `DATABASE_URL` environment variable

## Troubleshooting

### Bot doesn't create channels

- Ensure the admin group has forum topics enabled
- Verify the bot has admin permissions in the group
- Check that `ADMIN_GROUP_ID` is correct (must be negative for groups)

### Messages not being relayed

- Check bot logs for error messages
- Verify the bot is still in the admin group

### Database errors

- **SQLite**: Ensure the bot has write permissions in the directory
- **PostgreSQL**: Verify `DATABASE_URL` is correct and the database is accessible
- Check that the database schema was initialized correctly

### enjoy