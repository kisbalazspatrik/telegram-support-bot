"""Database persistence layer for ticket management. Supports both SQLite (LOCAL) and PostgreSQL (POSTGRES)."""
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any
import datetime

logger = logging.getLogger(__name__)

# Database-specific imports will be loaded lazily based on DB_TYPE
_connection_pool: Optional[Any] = None
DB_FILE = "tickets.db"


def _get_db_type():
    """Get DB_TYPE from config, ensuring config is loaded."""
    from config import Config
    return Config.DB_TYPE


def _ensure_postgres_imports():
    """Ensure PostgreSQL modules are imported."""
    try:
        import psycopg2
        from psycopg2 import pool, sql
        from psycopg2.extras import DictCursor, RealDictCursor
        return psycopg2, pool, sql, DictCursor, RealDictCursor
    except ImportError:
        raise ImportError(
            "psycopg2-binary is required for PostgreSQL. "
            "Install it with: pip install psycopg2-binary"
        )


def _ensure_sqlite_import():
    """Ensure SQLite module is imported."""
    import sqlite3
    return sqlite3


def get_connection_pool():
    """Initialize and return the PostgreSQL connection pool (only for POSTGRES)."""
    from config import Config
    
    if _get_db_type() != "POSTGRES":
        raise ValueError("Connection pool is only available for PostgreSQL")
    
    global _connection_pool
    
    if _connection_pool is None:
        _, pool_module, _, _, _ = _ensure_postgres_imports()
        
        if not Config.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required for PostgreSQL")
        
        try:
            _connection_pool = pool_module.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=Config.DATABASE_URL
            )
            logger.info("PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    
    return _connection_pool


@contextmanager
def get_db_connection():
    """Get a database connection with proper configuration."""
    db_type = _get_db_type()
    
    if db_type == "POSTGRES":
        pool = get_connection_pool()
        conn = pool.getconn()
        try:
            yield conn
            if not conn.closed:
                try:
                    conn.commit()
                except Exception:
                    conn.rollback()
        except Exception as e:
            if not conn.closed:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            pool.putconn(conn)
    elif db_type == "LOCAL":
        sqlite3 = _ensure_sqlite_import()
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    else:
        raise ValueError(f"Unsupported DB_TYPE: {db_type}")


def init_database():
    """Initialize the database schema if it doesn't exist."""
    db_type = _get_db_type()
    
    if db_type == "POSTGRES":
        _init_postgres()
    elif db_type == "LOCAL":
        _init_sqlite()
    else:
        raise ValueError(f"Unsupported DB_TYPE: {db_type}")


def _init_postgres():
    """Initialize PostgreSQL database schema."""
    _, _, sql_module, DictCursor, _ = _ensure_postgres_imports()
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        # Check if tickets table exists
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'tickets'
        """)
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            # Check if we need to migrate (old constraint without 'resolved')
            cursor.execute("""
                SELECT conname, pg_get_constraintdef(oid) as constraint_def
                FROM pg_constraint
                WHERE conrelid = (
                    SELECT oid FROM pg_class WHERE relname = 'tickets'
                )
                AND contype = 'c'
                AND pg_get_constraintdef(oid) LIKE '%status%'
            """)
            constraints = cursor.fetchall()
            
            needs_migration = False
            constraint_name = None
            for constraint in constraints:
                constraint_def = constraint.get('constraint_def', '')
                if "('open', 'closed')" in constraint_def and "'resolved'" not in constraint_def:
                    needs_migration = True
                    constraint_name = constraint.get('conname')
                    break
            
            if needs_migration:
                logger.info("Migrating database schema to support 'resolved' status...")
                if constraint_name:
                    cursor.execute(
                        sql_module.SQL("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS {}").format(
                            sql_module.Identifier(constraint_name)
                        )
                    )
                
                cursor.execute("""
                    ALTER TABLE tickets 
                    ADD CONSTRAINT tickets_status_check 
                    CHECK (status IN ('open', 'closed', 'resolved'))
                """)
                
                conn.commit()
                logger.info("Database migration completed successfully")
        else:
            # Create tickets table
            cursor.execute("""
                CREATE TABLE tickets (
                    ticket_number INTEGER PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username VARCHAR(255),
                    channel_id BIGINT NOT NULL UNIQUE,
                    status VARCHAR(20) DEFAULT 'open' CHECK(status IN ('open', 'closed', 'resolved')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP
                )
            """)
        
        # Create counter table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                value INTEGER DEFAULT 0
            )
        """)
        
        # Initialize counter if it doesn't exist
        cursor.execute("""
            INSERT INTO counter (id, value) 
            VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_channel_id ON tickets(channel_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        
        conn.commit()
        logger.info("PostgreSQL database initialized successfully")


def _init_sqlite():
    """Initialize SQLite database schema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create tickets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_number INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT,
                channel_id INTEGER NOT NULL UNIQUE,
                status TEXT DEFAULT 'open' CHECK(status IN ('open', 'closed', 'resolved')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
        
        # Create counter table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                value INTEGER DEFAULT 0
            )
        """)
        
        # Initialize counter if it doesn't exist
        cursor.execute("""
            INSERT OR IGNORE INTO counter (id, value) 
            VALUES (1, 0)
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_channel_id ON tickets(channel_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        
        conn.commit()
        logger.info("SQLite database initialized successfully")


def get_next_ticket_number() -> int:
    """Atomically increment and return the next ticket number."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, DictCursor, _ = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("UPDATE counter SET value = value + 1 WHERE id = 1")
            cursor.execute("SELECT value FROM counter WHERE id = 1")
            result = cursor.fetchone()
            ticket_number = result["value"]
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("UPDATE counter SET value = value + 1 WHERE id = 1")
            cursor.execute("SELECT value FROM counter WHERE id = 1")
            result = cursor.fetchone()
            ticket_number = result[0]
        
        logger.info(f"Generated ticket number: {ticket_number}")
        return ticket_number


def create_ticket(user_id: int, username: Optional[str], channel_id: int) -> int:
    """Create a new ticket record in the database."""
    db_type = _get_db_type()
    ticket_number = get_next_ticket_number()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, DictCursor, _ = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("""
                INSERT INTO tickets (ticket_number, user_id, username, channel_id, status)
                VALUES (%s, %s, %s, %s, 'open')
            """, (ticket_number, user_id, username, channel_id))
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tickets (ticket_number, user_id, username, channel_id, status)
                VALUES (?, ?, ?, ?, 'open')
            """, (ticket_number, user_id, username, channel_id))
        
        conn.commit()
        logger.info(f"Created ticket #{ticket_number} for user {user_id}")
    
    return ticket_number


def get_ticket_by_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Find a ticket by channel ID."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, _, RealDictCursor = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE channel_id = %s
            """, (channel_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE channel_id = ?
            """, (channel_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'ticket_number': row[0],
                    'user_id': row[1],
                    'username': row[2],
                    'channel_id': row[3],
                    'status': row[4],
                    'created_at': row[5],
                    'closed_at': row[6]
                }
        return None


def get_ticket_by_user(user_id: int, status: str = 'open') -> Optional[Dict[str, Any]]:
    """Find an active ticket for a user."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, _, RealDictCursor = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE user_id = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id, status))
            row = cursor.fetchone()
            if row:
                return dict(row)
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id, status))
            row = cursor.fetchone()
            if row:
                return {
                    'ticket_number': row[0],
                    'user_id': row[1],
                    'username': row[2],
                    'channel_id': row[3],
                    'status': row[4],
                    'created_at': row[5],
                    'closed_at': row[6]
                }
        return None


def get_ticket_by_number(ticket_number: int) -> Optional[Dict[str, Any]]:
    """Find a ticket by ticket number."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, _, RealDictCursor = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE ticket_number = %s
            """, (ticket_number,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticket_number, user_id, username, channel_id, status, created_at, closed_at
                FROM tickets
                WHERE ticket_number = ?
            """, (ticket_number,))
            row = cursor.fetchone()
            if row:
                return {
                    'ticket_number': row[0],
                    'user_id': row[1],
                    'username': row[2],
                    'channel_id': row[3],
                    'status': row[4],
                    'created_at': row[5],
                    'closed_at': row[6]
                }
        return None


def close_ticket(ticket_number: int) -> bool:
    """Close a ticket by updating its status."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        now = datetime.datetime.now()
        if db_type == "POSTGRES":
            _, _, _, DictCursor, _ = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("""
                UPDATE tickets
                SET status = 'closed', closed_at = %s
                WHERE ticket_number = %s
            """, (now, ticket_number))
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tickets
                SET status = 'closed', closed_at = ?
                WHERE ticket_number = ?
            """, (now, ticket_number))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            logger.info(f"Closed ticket #{ticket_number}")
            return True
        return False


def reopen_ticket(ticket_number: int) -> bool:
    """Reopen a closed ticket."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        if db_type == "POSTGRES":
            _, _, _, DictCursor, _ = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("""
                UPDATE tickets
                SET status = 'open', closed_at = NULL
                WHERE ticket_number = %s AND status = 'closed'
            """, (ticket_number,))
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tickets
                SET status = 'open', closed_at = NULL
                WHERE ticket_number = ? AND status = 'closed'
            """, (ticket_number,))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            logger.info(f"Reopened ticket #{ticket_number}")
            return True
        return False


def resolve_ticket(ticket_number: int) -> bool:
    """Resolve a ticket (mark as resolved, different from closed)."""
    db_type = _get_db_type()
    
    with get_db_connection() as conn:
        now = datetime.datetime.now()
        if db_type == "POSTGRES":
            _, _, _, DictCursor, _ = _ensure_postgres_imports()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("""
                UPDATE tickets
                SET status = 'resolved', closed_at = %s
                WHERE ticket_number = %s
            """, (now, ticket_number))
        else:  # SQLite
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tickets
                SET status = 'resolved', closed_at = ?
                WHERE ticket_number = ?
            """, (now, ticket_number))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            logger.info(f"Resolved ticket #{ticket_number}")
            return True
        return False


def sync_with_telegram(bot, admin_group_id: int) -> None:
    """
    Optional: Sync ticket counter with existing Telegram channels.
    This ensures continuity if database is reset but channels still exist.
    """
    try:
        # For now, we'll skip this as it requires additional API calls
        # and the database should be the source of truth
        logger.info("Telegram sync skipped - database is source of truth")
    except Exception as e:
        logger.warning(f"Failed to sync with Telegram: {e}")
