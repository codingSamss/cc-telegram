"""Tests for Claude integration facade fallback behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude.exceptions import ClaudeProcessError, ClaudeTimeoutError
from src.claude.facade import ClaudeIntegration
from src.claude.integration import ClaudeResponse
from src.config.settings import Settings


def _build_config(tmp_path, use_sdk: bool) -> Settings:
    """Create test config for facade tests."""
    return Settings(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=tmp_path,
        use_sdk=use_sdk,
        claude_timeout_seconds=2,
    )


def _build_facade(config: Settings, sdk_manager, process_manager) -> ClaudeIntegration:
    """Build facade with mocked managers."""
    return ClaudeIntegration(
        config=config,
        process_manager=process_manager,
        sdk_manager=sdk_manager,
        session_manager=MagicMock(),
        tool_monitor=MagicMock(),
        permission_manager=MagicMock(),
    )


class TestClaudeIntegrationFacade:
    """Test fallback behavior in ClaudeIntegration."""

    async def test_images_require_sdk_mode(self, tmp_path):
        """Image requests should fail fast when SDK mode is disabled."""
        config = _build_config(tmp_path, use_sdk=False)
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock()

        facade = _build_facade(
            config=config, sdk_manager=None, process_manager=process_manager
        )

        with pytest.raises(ClaudeProcessError) as exc_info:
            await facade._execute_with_fallback(
                prompt="Analyze this image",
                working_directory=tmp_path,
                images=[
                    {
                        "base64_data": "dGVzdA==",
                        "media_type": "image/jpeg",
                    }
                ],
            )

        assert "USE_SDK=true" in str(exc_info.value)
        process_manager.execute_command.assert_not_awaited()

    async def test_images_do_not_fallback_to_subprocess_on_sdk_error(self, tmp_path):
        """Image requests should not silently degrade to text-only subprocess mode."""
        config = _build_config(tmp_path, use_sdk=True)

        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock(
            side_effect=ClaudeTimeoutError("SDK timeout")
        )
        sdk_manager.execute_with_client = AsyncMock()

        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock()

        facade = _build_facade(
            config=config, sdk_manager=sdk_manager, process_manager=process_manager
        )

        with pytest.raises(ClaudeProcessError) as exc_info:
            await facade._execute_with_fallback(
                prompt="Analyze this image",
                working_directory=tmp_path,
                images=[
                    {
                        "base64_data": "dGVzdA==",
                        "media_type": "image/jpeg",
                    }
                ],
            )

        assert "cannot fall back to CLI text mode" in str(exc_info.value)
        process_manager.execute_command.assert_not_awaited()

    async def test_text_request_can_fallback_to_subprocess(self, tmp_path):
        """Non-image requests keep existing SDK->subprocess fallback behavior."""
        config = _build_config(tmp_path, use_sdk=True)

        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock(
            side_effect=ClaudeTimeoutError("SDK timeout")
        )
        sdk_manager.execute_with_client = AsyncMock()

        fallback_response = ClaudeResponse(
            content="fallback ok",
            session_id="fallback-session",
            cost=0.0,
            duration_ms=10,
            num_turns=1,
        )
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock(return_value=fallback_response)

        facade = _build_facade(
            config=config, sdk_manager=sdk_manager, process_manager=process_manager
        )

        result = await facade._execute_with_fallback(
            prompt="hello",
            working_directory=tmp_path,
            images=None,
        )

        assert result is fallback_response
        process_manager.execute_command.assert_awaited_once()

    async def test_text_request_with_permission_callback_still_uses_query_mode(
        self, tmp_path
    ):
        """When SDK is enabled, stability mode should bypass SDKClient path."""
        config = _build_config(tmp_path, use_sdk=True)

        query_response = ClaudeResponse(
            content="query ok",
            session_id="query-session",
            cost=0.0,
            duration_ms=12,
            num_turns=1,
        )

        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock(return_value=query_response)
        sdk_manager.execute_with_client = AsyncMock()

        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock()

        facade = _build_facade(
            config=config, sdk_manager=sdk_manager, process_manager=process_manager
        )

        result = await facade._execute_with_fallback(
            prompt="hello",
            working_directory=tmp_path,
            permission_callback=AsyncMock(),
            images=None,
        )

        assert result is query_response
        sdk_manager.execute_command.assert_awaited_once()
        sdk_manager.execute_with_client.assert_not_awaited()
