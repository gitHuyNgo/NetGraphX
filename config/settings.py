import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=True)

def get_env(key: str, default=None, required: bool = False):
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    
    return value


@dataclass(frozen=True)
class NetBoxConfig:
    NETBOX_URL: str = get_env("NETBOX_URL", "http://localhost:8081")
    NETBOX_API_TOKEN: str = get_env("NETBOX_API_TOKEN", required=True)


@dataclass(frozen=True)
class AppConfig:
    APP_NAME: str = "NetGraphX"
    DEBUG: bool = get_env("DEBUG", "true").lower() == "true"


@dataclass(frozen=True)
class Neo4jConfig:
    NEO4J_URI: str = get_env("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = get_env("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = get_env("NEO4J_PASSWORD", "")
    NEO4J_ENABLED: bool = get_env("NEO4J_ENABLED", "false").lower() == "true"


@dataclass(frozen=True)
class LLMConfig:
    OPENAI_API_KEY: str = get_env("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = get_env("OPENAI_MODEL", "gpt-4o-mini")


@dataclass(frozen=True)
class WebhookConfig:
    """Configuration for the debounced NetBox webhook receiver."""
    WEBHOOK_SECRET: str = get_env("WEBHOOK_SECRET", "")
    WEBHOOK_PORT: int = int(get_env("WEBHOOK_PORT", "5001"))
    # Minutes to wait since last NetBox change before triggering auto-sync.
    # Override in .env; do NOT hardcode this value.
    WEBHOOK_DEBOUNCE_MINUTES: int = int(get_env("WEBHOOK_DEBOUNCE_MINUTES", "10"))
    WEBHOOK_STATE_FILE: str = get_env("WEBHOOK_STATE_FILE", str(Path(__file__).parent.parent / "data" / "storage" / "webhook_state.json"))


@dataclass(frozen=True)
class AuthConfig:
    """Configuration for role-based access control."""
    USERS_FILE: str = get_env("USERS_FILE", "config/users.yaml")
    # Secret key used to sign session tokens / Streamlit session integrity
    SESSION_SECRET: str = get_env("SESSION_SECRET", "changeme-set-in-dotenv")


netbox_config = NetBoxConfig()
neo4j_config = Neo4jConfig()
app_config = AppConfig()
llm_config = LLMConfig()
webhook_config = WebhookConfig()
auth_config = AuthConfig()