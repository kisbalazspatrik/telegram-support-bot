# Resetting the Database

This guide covers how to reset the database for both SQLite (LOCAL) and PostgreSQL (POSTGRES) configurations.

## SQLite (LOCAL)

### Option 1: Delete the database file

Simply delete the `tickets.db` file:

```bash
rm tickets.db
```

The bot will automatically create a new database with the correct schema on next startup.

### Option 2: Using Python script

Create a reset script:

```python
import os

DB_FILE = "tickets.db"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
    print(f"✅ Deleted {DB_FILE}")
    print("Database will be recreated on next bot startup.")
else:
    print(f"❌ {DB_FILE} not found")
```

### Option 3: Reset counter only (keep tickets)

If you want to keep ticket history but reset the counter:

```python
import sqlite3

DB_FILE = "tickets.db"

with sqlite3.connect(DB_FILE) as conn:
    cursor = conn.cursor()
    cursor.execute("UPDATE counter SET value = 0 WHERE id = 1")
    conn.commit()
    print("✅ Counter reset to 0")
```

## PostgreSQL (POSTGRES)

### Option 1: Drop and recreate tables

Connect to your PostgreSQL database and run:

```sql
DROP TABLE IF EXISTS tickets CASCADE;
DROP TABLE IF EXISTS counter CASCADE;
```

The bot will automatically recreate the tables with the correct schema on next startup.

### Option 2: Truncate tables (keep schema)

If you want to keep the schema but remove all data:

```sql
TRUNCATE TABLE tickets;
UPDATE counter SET value = 0 WHERE id = 1;
```

### Option 3: Reset counter only (keep tickets)

```sql
UPDATE counter SET value = 0 WHERE id = 1;
```

### Option 4: Using Python script

```python
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment")
    exit(1)

try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Drop tables
    cursor.execute("DROP TABLE IF EXISTS tickets CASCADE")
    cursor.execute("DROP TABLE IF EXISTS counter CASCADE")
    
    conn.commit()
    print("✅ Database tables dropped")
    print("Tables will be recreated on next bot startup.")
    
    cursor.close()
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")
```

## What gets reset

When you reset the database:

- ✅ All tickets are deleted
- ✅ Ticket counter resets to 0
- ✅ Database schema is recreated automatically (on next bot startup)
- ✅ Next ticket will be #1

## Production deployment

For production, you typically want to:

1. Stop the bot
2. Backup the database:
   - **SQLite**: `cp tickets.db tickets.db.backup`
   - **PostgreSQL**: `pg_dump $DATABASE_URL > backup.sql`
3. Reset the database (using one of the methods above)
4. Start the bot (it will create a fresh database)

**⚠️ Warning:** Make sure to backup important data before resetting!

## Migration between database types

If you want to switch from SQLite to PostgreSQL (or vice versa):

1. Export data from the current database
2. Update `.env` with new `DB_TYPE` and `DATABASE_URL` (if switching to PostgreSQL)
3. Reset the new database (it will be empty)
4. Import data if needed (manual process - not automated)

Note: The bot does not provide automatic migration tools. You'll need to manually export/import data if you want to preserve ticket history.
