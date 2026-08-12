# env_loader.py - Environment configuration loader for Rival Gym System
import os
import sys
from dotenv import load_dotenv

def load_environment():
    # 1. Determine environment (default to DEV)
    app_env = os.environ.get('APP_ENV', '').strip().upper()

    # If APP_ENV is empty, check if a default .env file specifies it
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not app_env:
        default_env_path = os.path.join(root_dir, '.env')
        if os.path.exists(default_env_path):
            with open(default_env_path, 'r') as f:
                for line in f:
                    if line.strip().startswith('APP_ENV='):
                        app_env = line.strip().split('=', 1)[1].strip().upper()
                        break

    # Default to DEV if still not set
    if not app_env:
        app_env = 'DEV'

    # Normalize to standard values (DEV, TEST, PRODUCTION)
    if app_env in ['TESTING', 'TEST']:
        app_env = 'TEST'
    elif app_env in ['PROD', 'PRODUCTION']:
        app_env = 'PRODUCTION'
    else:
        app_env = 'DEV'

    # Set it in the environment so the rest of the application can read it
    os.environ['APP_ENV'] = app_env

    # 2. Load the corresponding .env file
    if app_env == 'TEST':
        dotenv_path = os.path.join(root_dir, '.env.testing')
    elif app_env == 'PRODUCTION':
        dotenv_path = os.path.join(root_dir, '.env')
    else: # DEV
        dotenv_path = os.path.join(root_dir, '.env.development')

    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path, override=True)
    else:
        # If the file doesn't exist, we log a warning but proceed
        # (Useful for production where env variables are set directly in Gunicorn/Railway)
        if app_env != 'PRODUCTION':
            print(f"WARNING: Environment file not found at {dotenv_path}. Falling back to existing system env.")

# Auto-execute on import
load_environment()
