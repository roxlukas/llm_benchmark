"""MySQL connection arguments with defaults taken from .env (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME).

Command-line flags still override .env, e.g. --database for the telco database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')


def add_db_args(parser):
    """Add --host/--port/--user/--password/--database; user and password are required only when .env lacks them."""
    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    parser.add_argument('--host', default=os.getenv('DB_HOST', 'localhost'), help='MySQL host (DB_HOST)')
    parser.add_argument('--port', type=int, default=int(os.getenv('DB_PORT', 3306)), help='MySQL port (DB_PORT)')
    parser.add_argument('--user', default=user, required=user is None, help='MySQL username (DB_USER)')
    parser.add_argument('--password', default=password, required=password is None, help='MySQL password (DB_PASSWORD)')
    parser.add_argument('--database', default=os.getenv('DB_NAME', 'llm_benchmark'), help='MySQL database name (DB_NAME)')
