"""Security bootstrap tests for main application wiring."""

import pytest

from src.config import create_test_config
from src.exceptions import ConfigurationError
from src.main import create_application


@pytest.mark.asyncio
async def test_create_application_fails_closed_without_auth_providers(tmp_path):
    """Application must not start when no authentication provider is configured."""
    config = create_test_config(
        approved_directory=str(tmp_path),
        database_url=f"sqlite:///{tmp_path / 'bot.db'}",
        allowed_users=None,
        development_mode=True,
    )

    with pytest.raises(
        ConfigurationError, match="No authentication providers configured"
    ):
        await create_application(config)
