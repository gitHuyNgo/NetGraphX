import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def get_env(key: str, default=None, required: bool = False):
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    
    return value


@dataclass(frozen=True)
class NetBoxConfig:
    NETBOX_URL: str = get_env("NETBOX_URL", "http://localhost:8000")
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


netbox_config = NetBoxConfig()
neo4j_config = Neo4jConfig()
app_config = AppConfig()
llm_config = LLMConfig()