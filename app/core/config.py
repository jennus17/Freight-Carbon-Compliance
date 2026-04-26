from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ESG_", extra="ignore")

    app_name: str = "ESG Carbon API"
    app_version: str = "0.3.0"
    description: str = (
        "REST API for calculating logistics carbon footprint (CO2e) "
        "in alignment with EU CSRD / ESRS E1 disclosure requirements. "
        "Supports DEFRA 2023, 2024 and 2025 vintages; alternative fuels "
        "(HVO, SAF, LNG, methanol, electric); regional grid factors; "
        "Stripe-style idempotency; and bulk calculation."
    )
    api_v1_prefix: str = "/api/v1"

    # ── RapidAPI gateway integration ────────────────────────────────────
    # When set, every request to /api/v1/* must carry the matching
    # `X-RapidAPI-Proxy-Secret` header — this stops anyone bypassing the
    # RapidAPI gateway (and our billing) by hitting the origin directly.
    # Leave empty in dev to disable the check.
    rapidapi_proxy_secret: str = ""

    # ── Observability ───────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"        # "json" for prod, "console" for dev readability
    metrics_enabled: bool = True
    request_id_header: str = "X-Request-ID"


settings = Settings()
