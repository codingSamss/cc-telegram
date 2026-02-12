"""Tests for Claude integration facade fallback behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude.exceptions import ClaudeProcessError, ClaudeTimeoutError
from src.claude.facade import ClaudeIntegration
from src.claude.integration import ClaudeResponse
from src.config.settings import Settings


def _build_config(tmp_path, use_sdk: bool, **overrides) -> Settings:
    """Create test config for facade tests."""
    payload = dict(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=tmp_path,
        use_sdk=use_sdk,
        claude_timeout_seconds=2,
    )
    payload.update(overrides)
    return Settings(**payload)


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

    async def test_get_precise_context_usage_parses_and_uses_cache(self, tmp_path):
        """Exact context probe should parse /context output and cache by session."""
        config = _build_config(
            tmp_path,
            use_sdk=True,
            status_context_probe_ttl_seconds=60,
        )
        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock()
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content=(
                    "Context usage: 27.5% (55,000 / 200,000 tokens)\n"
                    "Remaining: 145,000 tokens"
                ),
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )

        facade = _build_facade(config, sdk_manager, process_manager)
        first = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
            model="sonnet",
        )
        second = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
            model="sonnet",
        )

        assert first is not None
        assert first["used_tokens"] == 55_000
        assert first["total_tokens"] == 200_000
        assert first["remaining_tokens"] == 145_000
        assert first["used_percent"] == 27.5
        assert first["cached"] is False

        assert second is not None
        assert second["cached"] is True
        process_manager.execute_command.assert_awaited_once()
        sdk_manager.execute_command.assert_not_awaited()

    async def test_get_precise_context_usage_returns_none_when_unparseable(
        self, tmp_path
    ):
        """Unparseable /context output should fail safely without cache hit."""
        config = _build_config(
            tmp_path,
            use_sdk=True,
            status_context_probe_ttl_seconds=60,
        )
        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content="No context details available",
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content="No context details available",
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )

        facade = _build_facade(config, sdk_manager, process_manager)
        first = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
        )
        second = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
        )

        assert first is None
        assert second is None
        assert sdk_manager.execute_command.await_count == 2
        assert process_manager.execute_command.await_count == 2

    async def test_get_precise_context_usage_no_cache_when_ttl_zero(self, tmp_path):
        """TTL=0 should force realtime probe on every /status call."""
        config = _build_config(
            tmp_path,
            use_sdk=True,
            status_context_probe_ttl_seconds=0,
        )
        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock()
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content="Context usage: 20% (40,000 / 200,000 tokens)",
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )

        facade = _build_facade(config, sdk_manager, process_manager)
        first = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
        )
        second = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
        )

        assert first is not None
        assert second is not None
        assert first["cached"] is False
        assert second["cached"] is False
        assert process_manager.execute_command.await_count == 2
        sdk_manager.execute_command.assert_not_awaited()

    async def test_get_precise_context_usage_falls_back_to_sdk_probe(self, tmp_path):
        """SDK probe should run when subprocess probe fails/unparseable."""
        config = _build_config(
            tmp_path,
            use_sdk=True,
            status_context_probe_ttl_seconds=0,
        )
        process_manager = MagicMock()
        process_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content="",
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )
        sdk_manager = MagicMock()
        sdk_manager.execute_command = AsyncMock(
            return_value=ClaudeResponse(
                content="Context usage: 10% (20,000 / 200,000 tokens)",
                session_id="session-1",
                cost=0.0,
                duration_ms=1,
                num_turns=0,
            )
        )

        facade = _build_facade(config, sdk_manager, process_manager)
        payload = await facade.get_precise_context_usage(
            session_id="session-1",
            working_directory=tmp_path,
        )

        assert payload is not None
        assert payload["used_tokens"] == 20_000
        process_manager.execute_command.assert_awaited_once()
        sdk_manager.execute_command.assert_awaited_once()

    def test_parse_context_usage_text_supports_labeled_lines(self, tmp_path):
        """Parser should support non-slash labeled context formats."""
        config = _build_config(tmp_path, use_sdk=False)
        facade = _build_facade(config, sdk_manager=None, process_manager=MagicMock())

        payload = facade._parse_context_usage_text(
            "Context usage\nUsed: 32,536 tokens\nWindow: 200,000 tokens\nRemaining: 167,464 tokens"
        )

        assert payload is not None
        assert payload["used_tokens"] == 32_536
        assert payload["total_tokens"] == 200_000
        assert payload["remaining_tokens"] == 167_464

    def test_parse_context_usage_text_can_infer_total_from_used_and_percent(self, tmp_path):
        """Parser should infer totals when only used+percent are provided."""
        config = _build_config(tmp_path, use_sdk=False)
        facade = _build_facade(config, sdk_manager=None, process_manager=MagicMock())

        payload = facade._parse_context_usage_text(
            "已使用 40,000 tokens (20%)，剩余 160,000 tokens"
        )

        assert payload is not None
        assert payload["used_tokens"] == 40_000
        assert payload["total_tokens"] == 200_000
        assert payload["remaining_tokens"] == 160_000
