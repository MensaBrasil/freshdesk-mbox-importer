"""Settings for Freshdesk MBOX Importer."""

from pydantic_settings import BaseSettings

class ImporterSettings(BaseSettings):
    """Load Freshdesk importer settings from .env."""
    fd_domain: str
    fd_key: str
    mbox_path: str = "takeout.mbox"
    original_date_field: str = "cf_original_date"
    rate_delay: float = 0.8
    mbox_owner_email: str
    import_group_name: str = "imported"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }