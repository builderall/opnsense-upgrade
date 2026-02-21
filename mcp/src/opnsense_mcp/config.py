"""Configuration: loads from mcp/.env or environment variables."""

import os
from pathlib import Path
from pydantic import BaseModel


def _load_env_file():
    """Load .env file from the mcp/ directory (parent of src/)."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


class Config(BaseModel):
    url: str
    api_key: str
    api_secret: str
    verify_ssl: bool = False
    read_only: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        url = os.environ.get("OPNSENSE_URL", "").rstrip("/")
        if not url:
            raise ValueError("OPNSENSE_URL is not set. Check mcp/.env or environment.")
        api_key = os.environ.get("OPNSENSE_API_KEY", "")
        if not api_key:
            raise ValueError("OPNSENSE_API_KEY is not set.")
        api_secret = os.environ.get("OPNSENSE_API_SECRET", "")
        if not api_secret:
            raise ValueError("OPNSENSE_API_SECRET is not set.")
        verify_ssl_str = os.environ.get("OPNSENSE_VERIFY_SSL", "false").lower()
        verify_ssl = verify_ssl_str in ("1", "true", "yes")
        read_only_str = os.environ.get("OPNSENSE_READ_ONLY", "false").lower()
        read_only = read_only_str in ("1", "true", "yes")
        return cls(
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            verify_ssl=verify_ssl,
            read_only=read_only,
        )
