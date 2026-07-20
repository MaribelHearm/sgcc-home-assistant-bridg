import logging
import os
from dataclasses import dataclass, field


_MQTT_LEGACY_DISCOVERY_MODES = {"compat", "off", "cleanup"}


def _mqtt_legacy_discovery_mode() -> str:
    value = os.getenv("MQTT_LEGACY_DISCOVERY_MODE", "compat").strip().lower()
    if value in _MQTT_LEGACY_DISCOVERY_MODES:
        return value
    logging.warning(
        "未知 MQTT_LEGACY_DISCOVERY_MODE=%r，回退为 compat。",
        value,
    )
    return "compat"


@dataclass
class FetcherConfig:
    DRIVER_IMPLICITY_WAIT_TIME: int = 60
    RETRY_TIMES_LIMIT: int = 5
    LOGIN_EXPECTED_TIME: int = 10
    RETRY_WAIT_TIME_OFFSET_UNIT: int = 10
    IGNORE_USER_ID: list[str] = field(default_factory=list)
    PAGE_LOAD_TIMEOUT: int = 45
    QR_CODE_LOGIN_WAIT_COUNT: int = 7
    QR_CODE_LOGIN_WAIT_TIME_INTERVAL_UNIT: int = 10
    user_name_map: dict[str, str] = field(default_factory=dict)
    PUBLISHER: str = "mqtt"
    MQTT_HOST: str = ""
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    MQTT_DISCOVERY_PREFIX: str = "homeassistant"
    MQTT_LEGACY_DISCOVERY_MODE: str = "compat"

    @classmethod
    def from_env(cls) -> "FetcherConfig":
        if 'PYTHON_IN_DOCKER' not in os.environ:
            import dotenv
            dotenv.load_dotenv(verbose=True)

        user_name_map = {}
        raw_names = os.getenv("USER_NAMES", "")
        if raw_names:
            for pair in raw_names.split(","):
                if ":" in pair:
                    uid, name = pair.split(":", 1)
                    user_name_map[uid.strip()] = name.strip()

        return cls(
            DRIVER_IMPLICITY_WAIT_TIME=int(os.getenv("DRIVER_IMPLICITY_WAIT_TIME", 60)),
            RETRY_TIMES_LIMIT=int(os.getenv("RETRY_TIMES_LIMIT", 5)),
            LOGIN_EXPECTED_TIME=int(os.getenv("LOGIN_EXPECTED_TIME", 10)),
            RETRY_WAIT_TIME_OFFSET_UNIT=int(os.getenv("RETRY_WAIT_TIME_OFFSET_UNIT", 10)),
            IGNORE_USER_ID=[uid.strip() for uid in os.getenv("IGNORE_USER_ID", "").split(",") if uid.strip()],
            PAGE_LOAD_TIMEOUT=int(os.getenv("PAGE_LOAD_TIMEOUT", 45)),
            QR_CODE_LOGIN_WAIT_COUNT=int(os.getenv("QR_CODE_LOGIN_WAIT_COUNT", 7)),
            QR_CODE_LOGIN_WAIT_TIME_INTERVAL_UNIT=int(os.getenv("QR_CODE_LOGIN_WAIT_TIME_INTERVAL_UNIT", 10)),
            user_name_map=user_name_map,
            PUBLISHER=os.getenv("PUBLISHER", "mqtt").strip().lower(),
            MQTT_HOST=os.getenv("MQTT_HOST", ""),
            MQTT_PORT=int(os.getenv("MQTT_PORT", 1883)),
            MQTT_USERNAME=os.getenv("MQTT_USERNAME", ""),
            MQTT_PASSWORD=os.getenv("MQTT_PASSWORD", ""),
            MQTT_DISCOVERY_PREFIX=os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
            MQTT_LEGACY_DISCOVERY_MODE=_mqtt_legacy_discovery_mode(),
        )
