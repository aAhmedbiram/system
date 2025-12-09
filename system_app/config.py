"""
Configuration Management for Rival Gym System
"""

import os
from datetime import timedelta

class Config:
    """Base configuration"""
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32)
    
    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('PGURL')
    
    # External APIs
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
    # Email Configuration
    GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')
    
    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # Rate Limiting
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_LOCKOUT_TIME = timedelta(minutes=15)
    
    # Activity Tracking
    ACTIVITY_TIMEOUT = timedelta(minutes=5)
    
    # Logging
    LOG_DIR = 'logs'
    LOG_FILE = 'rival_gym.log'
    LOG_MAX_BYTES = 10240000  # 10MB
    LOG_BACKUP_COUNT = 10
    
    # Pagination
    MEMBERS_PER_PAGE = 50
    ATTENDANCE_PER_PAGE = 50
    
    # Performance
    DB_POOL_MIN_CONN = 1
    DB_POOL_MAX_CONN = 20

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SESSION_COOKIE_SECURE = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    
    # Override with environment variables in production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY must be set in production!")

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    DATABASE_URL = os.environ.get('TEST_DATABASE_URL', 'postgresql://test:test@localhost/test_db')

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Get configuration based on environment"""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])

