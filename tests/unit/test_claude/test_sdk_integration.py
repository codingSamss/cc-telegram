"""Test Claude SDK integration."""

import os
from collections.abc import AsyncIterable
from pathlib import Path
from unittest.mock import patch

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from src.claude.sdk_integration import ClaudeResponse, ClaudeSDKManager, StreamUpdate
from src.config.settings import Settings


def _make_assistant_message(text="Test response"):
    """Create an AssistantMessage with proper structure for current SDK version."""
    return AssistantMessage(
        content=[TextBlock(text=text)],
        model="claude-sonnet-4-20250514",
    )


def _make_result_message(**kwargs):
    """Create a ResultMessage with sensible defaults."""
    defaults = {
        "subtype": "success",
        "duration_ms": 1000,
        "duration_api_ms": 800,
        "is_error": False,
        "num_turns": 1,
        "session_id": "test-session",
        "total_cost_usd": 0.05,
        "result": "Success",
    }
    defaults.update(kwargs)
    return ResultMessage(**defaults)


class TestClaudeSDKManager:
    """Test Claude SDK manager."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config without API key."""
        return Settings(
            telegram_bot_token="test:token",
            telegram_bot_username="testbot",
            approved_directory=tmp_path,
            use_sdk=True,
            claude_timeout_seconds=2,  # Short timeout for testing
        )

    @pytest.fixture
    def sdk_manager(self, config):
        """Create SDK manager."""
        return ClaudeSDKManager(config)

    async def test_sdk_manager_initialization_with_api_key(self, tmp_path):
        """Test SDK manager initialization with API key."""
        from src.config.settings import Settings

        # Test with API key provided
        config_with_key = Settings(
            telegram_bot_token="test:token",
            telegram_bot_username="testbot",
            approved_directory=tmp_path,
            anthropic_api_key="test-api-key",
            use_sdk=True,
            claude_timeout_seconds=2,
        )

        # Store original env var
        original_api_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            manager = ClaudeSDKManager(config_with_key)

            # Check that API key was set in environment
            assert os.environ.get("ANTHROPIC_API_KEY") == "test-api-key"
            assert manager.active_sessions == {}

        finally:
            # Restore original env var
            if original_api_key:
                os.environ["ANTHROPIC_API_KEY"] = original_api_key
            elif "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

    async def test_sdk_manager_initialization_without_api_key(self, config):
        """Test SDK manager initialization without API key (uses CLI auth)."""
        # Store original env var
        original_api_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            # Remove any existing API key
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            manager = ClaudeSDKManager(config)

            # Check that no API key was set (should use CLI auth)
            assert config.anthropic_api_key_str is None
            assert manager.active_sessions == {}

        finally:
            # Restore original env var
            if original_api_key:
                os.environ["ANTHROPIC_API_KEY"] = original_api_key

    async def test_sdk_manager_initialization_unsets_claudecode(self, config):
        """SDK manager should clear CLAUDECODE to avoid nested CLI runtime errors."""
        original_claudecode = os.environ.get("CLAUDECODE")
        os.environ["CLAUDECODE"] = "nested-session"

        try:
            ClaudeSDKManager(config)
            assert "CLAUDECODE" not in os.environ
        finally:
            if original_claudecode is not None:
                os.environ["CLAUDECODE"] = original_claudecode
            else:
                os.environ.pop("CLAUDECODE", None)

    async def test_execute_command_success(self, sdk_manager):
        """Test successful command execution."""

        async def mock_query(prompt, options):
            yield _make_assistant_message("Test response")
            yield _make_result_message(session_id="test-session", total_cost_usd=0.05)

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            response = await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
                session_id="test-session",
            )

        # Verify response
        assert isinstance(response, ClaudeResponse)
        assert response.session_id == "test-session"
        assert response.duration_ms >= 0  # Can be 0 in tests
        assert not response.is_error
        assert response.cost == 0.05

    async def test_execute_command_falls_back_to_result_text(self, sdk_manager):
        """When assistant text is empty, ResultMessage.result should be used."""

        async def mock_query(prompt, options):
            yield _make_result_message(
                session_id="test-session",
                total_cost_usd=0.0,
                result="Context (claude-opus-4-6)\nUsage: 32,536 / 200,000 (16.3%)",
            )

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            response = await sdk_manager.execute_command(
                prompt="/context",
                working_directory=Path("/test"),
                session_id="test-session",
                continue_session=True,
            )

        assert "Usage: 32,536 / 200,000 (16.3%)" in response.content

    async def test_execute_command_falls_back_to_local_command_stdout(
        self, sdk_manager
    ):
        """Extract stdout from UserMessage when ResultMessage.result is empty."""

        async def mock_query(prompt, options):
            yield UserMessage(
                content=(
                    "<local-command-stdout>"
                    "Context usage: 14% (28.8k / 200k tokens)"
                    "</local-command-stdout>"
                )
            )
            yield _make_result_message(
                session_id="test-session",
                total_cost_usd=0.0,
                result="",
            )

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            response = await sdk_manager.execute_command(
                prompt="/context",
                working_directory=Path("/test"),
                session_id="test-session",
                continue_session=True,
            )

        assert "28.8k / 200k" in response.content

    async def test_execute_command_leaves_setting_sources_unset_by_default(
        self, config
    ):
        """Default behavior should keep setting_sources unset for compatibility."""
        config.claude_setting_sources = None
        sdk_manager = ClaudeSDKManager(config)
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        assert len(captured_options) == 1
        assert captured_options[0].setting_sources in (None, [])

    async def test_execute_command_uses_configured_setting_sources(self, config):
        """Configured setting sources should be passed into ClaudeAgentOptions."""
        config.claude_setting_sources = ["user", "project", "local"]
        sdk_manager = ClaudeSDKManager(config)
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        assert len(captured_options) == 1
        assert captured_options[0].setting_sources == ["user", "project", "local"]

    async def test_execute_command_uses_user_settings_default_model(
        self, sdk_manager, tmp_path, monkeypatch
    ):
        """When no /model override, use default model from ~/.claude/settings.json."""
        home_dir = tmp_path / "home"
        settings_dir = home_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(
            '{"model":"opus"}',
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home_dir))
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        assert len(captured_options) == 1
        assert captured_options[0].model == "opus"

    async def test_execute_command_prefers_explicit_model_over_settings_default(
        self, sdk_manager, tmp_path, monkeypatch
    ):
        """Explicit /model should override settings default model."""
        home_dir = tmp_path / "home"
        settings_dir = home_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(
            '{"model":"opus"}',
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home_dir))
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
                model="sonnet",
            )

        assert len(captured_options) == 1
        assert captured_options[0].model == "sonnet"

    async def test_execute_command_with_images_uses_async_iterable_prompt(
        self, sdk_manager
    ):
        """Test multimodal path passes an AsyncIterable prompt (not coroutine)."""
        captured_message = None

        async def mock_query(prompt, options):
            nonlocal captured_message
            assert isinstance(prompt, AsyncIterable)

            async for msg in prompt:
                captured_message = msg
                break

            yield _make_assistant_message("Image response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Describe this image",
                working_directory=Path("/test"),
                images=[
                    {
                        "base64_data": "dGVzdA==",
                        "media_type": "image/jpeg",
                    }
                ],
            )

        assert captured_message is not None
        assert captured_message["type"] == "user"
        assert captured_message["message"]["role"] == "user"
        content_blocks = captured_message["message"]["content"]
        assert content_blocks[0]["type"] == "image"
        assert content_blocks[0]["source"]["media_type"] == "image/jpeg"
        assert content_blocks[1]["type"] == "text"
        assert content_blocks[1]["text"] == "Describe this image"

    async def test_execute_command_with_streaming(self, sdk_manager):
        """Test command execution with streaming callback."""
        stream_updates = []

        async def stream_callback(update: StreamUpdate):
            stream_updates.append(update)

        async def mock_query(prompt, options):
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
                stream_callback=stream_callback,
            )

        # Verify streaming was called
        assert len(stream_updates) > 0
        assert any(update.type == "assistant" for update in stream_updates)

    async def test_execute_command_emits_resolved_model_update(self, sdk_manager):
        """SDK mode should emit resolved model once first assistant message arrives."""
        stream_updates = []

        async def stream_callback(update: StreamUpdate):
            stream_updates.append(update)

        async def mock_query(prompt, options):
            yield _make_assistant_message("Test response")
            yield _make_result_message()

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
                stream_callback=stream_callback,
            )

        resolved_updates = [
            u
            for u in stream_updates
            if u.type == "system"
            and u.metadata
            and u.metadata.get("subtype") == "model_resolved"
        ]
        assert len(resolved_updates) == 1
        assert resolved_updates[0].metadata.get("model") == "claude-sonnet-4-20250514"

    async def test_handle_stream_message_emits_tool_events(self, sdk_manager):
        """Tool use/result blocks should become stream updates."""
        updates = []

        async def stream_callback(update: StreamUpdate):
            updates.append(update)

        message = AssistantMessage(
            content=[
                ToolUseBlock(
                    id="toolu_123",
                    name="Read",
                    input={"file_path": "README.md"},
                ),
                ToolResultBlock(
                    tool_use_id="toolu_123",
                    content="ok",
                    is_error=False,
                ),
                TextBlock(text="Done"),
            ],
            model="claude-sonnet-4-20250514",
        )

        await sdk_manager._handle_stream_message(message, stream_callback)

        assert any(u.type == "assistant" and u.tool_calls for u in updates)
        assert any(u.type == "tool_result" for u in updates)

    async def test_handle_stream_message_emits_init_when_capabilities_present(
        self, sdk_manager
    ):
        """Forward SDK SystemMessage init when capability metadata exists."""
        updates = []

        async def stream_callback(update: StreamUpdate):
            updates.append(update)

        message = SystemMessage(
            subtype="init",
            data={
                "subtype": "init",
                "supportsEffort": True,
                "supportedEffortLevels": ["low", "high"],
                "supportsAdaptiveThinking": False,
                "permissionMode": "default",
            },
        )

        await sdk_manager._handle_stream_message(message, stream_callback)

        assert len(updates) == 1
        assert updates[0].type == "system"
        assert updates[0].metadata is not None
        assert updates[0].metadata.get("subtype") == "init"
        assert updates[0].metadata.get("supportsEffort") is True
        assert updates[0].metadata.get("supports_effort") is True
        assert updates[0].metadata.get("supportedEffortLevels") == ["low", "high"]
        assert updates[0].metadata.get("supported_effort_levels") == ["low", "high"]
        assert updates[0].metadata.get("supportsAdaptiveThinking") is False
        assert updates[0].metadata.get("supports_adaptive_thinking") is False
        assert updates[0].metadata.get("permission_mode") == "default"

    async def test_handle_stream_message_passes_through_sdk_init(self, sdk_manager):
        """SDK init event should pass through with real tools/capabilities."""
        updates = []

        async def stream_callback(update: StreamUpdate):
            updates.append(update)

        message = SystemMessage(
            subtype="init",
            data={
                "subtype": "init",
                "tools": ["Read"],
                "cwd": "/test",
            },
        )

        await sdk_manager._handle_stream_message(message, stream_callback)

        assert len(updates) == 1
        assert updates[0].metadata["subtype"] == "init"
        assert updates[0].metadata["tools"] == ["Read"]

    async def test_execute_command_timeout(self, sdk_manager):
        """Test command execution timeout."""
        import asyncio

        # Mock a hanging operation - return async generator that never yields
        async def mock_hanging_query(prompt, options):
            await asyncio.sleep(5)  # This should timeout (config has 2s timeout)
            yield  # This will never be reached

        from src.claude.exceptions import ClaudeTimeoutError

        with patch("src.claude.sdk_integration.query", side_effect=mock_hanging_query):
            with pytest.raises(ClaudeTimeoutError):
                await sdk_manager.execute_command(
                    prompt="Test prompt",
                    working_directory=Path("/test"),
                )

    async def test_execute_with_client_stops_after_result_message(self, sdk_manager):
        """Client mode should stop reading stream once ResultMessage is received."""

        class FakeClient:
            instances = []

            def __init__(self, options):
                self.options = options
                self.disconnected = False
                FakeClient.instances.append(self)

            async def connect(self):
                return None

            async def query(self, prompt):
                self.prompt = prompt

            async def receive_response(self):
                yield _make_assistant_message("Client response")
                yield _make_result_message(
                    session_id="client-session",
                    total_cost_usd=0.02,
                )
                yield _make_assistant_message("Should be ignored")

            async def disconnect(self):
                self.disconnected = True

        with patch("src.claude.sdk_integration.ClaudeSDKClient", FakeClient):
            response = await sdk_manager.execute_with_client(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        assert response.session_id == "client-session"
        assert "Client response" in response.content
        assert "Should be ignored" not in response.content
        assert FakeClient.instances[0].disconnected is True

    async def test_execute_with_client_times_out_while_receiving(self, sdk_manager):
        """Client mode should timeout if receive_response hangs."""
        import asyncio

        class HangingClient:
            instances = []

            def __init__(self, options):
                self.options = options
                self.disconnected = False
                HangingClient.instances.append(self)

            async def connect(self):
                return None

            async def query(self, prompt):
                self.prompt = prompt

            async def receive_response(self):
                await asyncio.sleep(5)
                if False:
                    yield None

            async def disconnect(self):
                self.disconnected = True

        from src.claude.exceptions import ClaudeTimeoutError

        with patch("src.claude.sdk_integration.ClaudeSDKClient", HangingClient):
            with pytest.raises(ClaudeTimeoutError):
                await sdk_manager.execute_with_client(
                    prompt="Test prompt",
                    working_directory=Path("/test"),
                )

        assert HangingClient.instances[0].disconnected is True

    async def test_execute_with_client_disconnect_timeout_is_non_fatal(
        self, sdk_manager
    ):
        """Slow disconnect should be logged but must not fail successful response."""
        import asyncio

        class SlowDisconnectClient:
            instances = []

            def __init__(self, options):
                self.options = options
                self.disconnect_called = False
                SlowDisconnectClient.instances.append(self)

            async def connect(self):
                return None

            async def query(self, prompt):
                self.prompt = prompt

            async def receive_response(self):
                yield _make_assistant_message("Client ok")
                yield _make_result_message(session_id="client-ok")

            async def disconnect(self):
                self.disconnect_called = True
                await asyncio.sleep(5)

        with patch(
            "src.claude.sdk_integration.ClaudeSDKClient",
            SlowDisconnectClient,
        ):
            response = await sdk_manager.execute_with_client(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        assert response.session_id == "client-ok"
        assert "Client ok" in response.content
        assert SlowDisconnectClient.instances[0].disconnect_called is True

    async def test_session_management(self, sdk_manager):
        """Test session management."""
        session_id = "test-session"
        messages = [_make_assistant_message("test")]

        # Update session
        sdk_manager._update_session(session_id, messages)

        # Verify session was created
        assert session_id in sdk_manager.active_sessions
        session_data = sdk_manager.active_sessions[session_id]
        assert session_data["messages"] == messages

    async def test_kill_all_processes(self, sdk_manager):
        """Test killing all processes (clearing sessions)."""
        # Add some active sessions
        sdk_manager.active_sessions["session1"] = {"test": "data"}
        sdk_manager.active_sessions["session2"] = {"test": "data2"}

        assert len(sdk_manager.active_sessions) == 2

        # Kill all processes
        await sdk_manager.kill_all_processes()

        # Sessions should be cleared
        assert len(sdk_manager.active_sessions) == 0

    def test_get_active_process_count(self, sdk_manager):
        """Test getting active process count."""
        assert sdk_manager.get_active_process_count() == 0

        # Add sessions
        sdk_manager.active_sessions["session1"] = {"test": "data"}
        sdk_manager.active_sessions["session2"] = {"test": "data2"}

        assert sdk_manager.get_active_process_count() == 2

    async def test_execute_command_passes_mcp_config(self, tmp_path):
        """Test that MCP config is passed to ClaudeAgentOptions when enabled."""
        # Create a valid MCP config file
        mcp_config_file = tmp_path / "mcp_config.json"
        mcp_config_file.write_text(
            '{"mcpServers": {"test-server": {"command": "echo", "args": ["hello"]}}}'
        )

        config = Settings(
            telegram_bot_token="test:token",
            telegram_bot_username="testbot",
            approved_directory=tmp_path,
            use_sdk=True,
            claude_timeout_seconds=2,
            enable_mcp=True,
            mcp_config_path=str(mcp_config_file),
        )

        manager = ClaudeSDKManager(config)

        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message(total_cost_usd=0.01)

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await manager.execute_command(
                prompt="Test prompt",
                working_directory=tmp_path,
            )

        # Verify MCP config was parsed and passed as dict to options
        assert len(captured_options) == 1
        assert captured_options[0].mcp_servers == {
            "test-server": {"command": "echo", "args": ["hello"]}
        }

    async def test_execute_command_no_mcp_when_disabled(self, sdk_manager):
        """Test that MCP config is NOT passed when MCP is disabled."""
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield _make_assistant_message("Test response")
            yield _make_result_message(total_cost_usd=0.01)

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            await sdk_manager.execute_command(
                prompt="Test prompt",
                working_directory=Path("/test"),
            )

        # Verify MCP config was NOT set (should be empty default)
        assert len(captured_options) == 1
        assert captured_options[0].mcp_servers == {}


class TestClaudeMCPErrors:
    """Test MCP-specific error handling."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return Settings(
            telegram_bot_token="test:token",
            telegram_bot_username="testbot",
            approved_directory=tmp_path,
            use_sdk=True,
            claude_timeout_seconds=2,
        )

    @pytest.fixture
    def sdk_manager(self, config):
        """Create SDK manager."""
        return ClaudeSDKManager(config)

    async def test_mcp_connection_error_raises_mcp_error(self, sdk_manager):
        """Test that MCP connection errors raise ClaudeMCPError."""
        from claude_agent_sdk import CLIConnectionError

        from src.claude.exceptions import ClaudeMCPError

        async def mock_query(prompt, options):
            raise CLIConnectionError("MCP server failed to start")
            yield  # make it an async generator

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            with pytest.raises(ClaudeMCPError) as exc_info:
                await sdk_manager.execute_command(
                    prompt="Test prompt",
                    working_directory=Path("/test"),
                )

        assert "MCP server" in str(exc_info.value)

    async def test_mcp_process_error_raises_mcp_error(self, sdk_manager):
        """Test that MCP process errors raise ClaudeMCPError."""
        from claude_agent_sdk import ProcessError

        from src.claude.exceptions import ClaudeMCPError

        async def mock_query(prompt, options):
            raise ProcessError("Failed to start MCP server: connection refused")
            yield  # make it an async generator

        with patch("src.claude.sdk_integration.query", side_effect=mock_query):
            with pytest.raises(ClaudeMCPError) as exc_info:
                await sdk_manager.execute_command(
                    prompt="Test prompt",
                    working_directory=Path("/test"),
                )

        assert "MCP" in str(exc_info.value)
