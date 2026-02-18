"""Configuration management for the Telegram concierge bot."""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Bot configuration loaded from environment variables."""
    
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")
    DB_TYPE = os.getenv("DB_TYPE", "LOCAL").upper()  # LOCAL or POSTGRES
    DATABASE_URL = os.getenv("DATABASE_URL")  # Required only for POSTGRES
    
    @classmethod
    def validate(cls):
        """Validate that all required configuration is present."""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required")
        
        if not cls.ADMIN_GROUP_ID:
            raise ValueError("ADMIN_GROUP_ID environment variable is required")
        
        # Validate DB_TYPE
        if cls.DB_TYPE not in ("LOCAL", "POSTGRES"):
            raise ValueError("DB_TYPE must be either 'LOCAL' or 'POSTGRES'")
        
        # DATABASE_URL is required only for POSTGRES
        if cls.DB_TYPE == "POSTGRES" and not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required when DB_TYPE=POSTGRES")
        
        # Validate ADMIN_GROUP_ID is numeric (Telegram group/channel IDs are integers)
        try:
            int(cls.ADMIN_GROUP_ID)
        except ValueError:
            raise ValueError("ADMIN_GROUP_ID must be a valid integer")
        
        return True
