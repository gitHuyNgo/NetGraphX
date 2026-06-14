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


netbox_config = NetBoxConfig()
app_config = AppConfig()