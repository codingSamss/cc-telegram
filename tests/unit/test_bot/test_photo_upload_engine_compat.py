"""Tests for photo upload engine compatibility guardrails."""

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.message import _integration_supports_image_analysis, handle_photo
from src.bot.utils.cli_engine import ENGINE_STATE_KEY
from src.config.settings import Settings


def _scope_key(user_id: int) -> str:
    return f"{user_id}:{user_id}:0"


class _FakeFeatures:
    """Minimal features adapter exposing image handler."""

    def __init__(self, image_handler):
        self._image_handler = image_handler

    def get_image_handler(self):
        return self._image_handler


def _build_update_and_progress(user_id: int):
    progress_msg = SimpleNamespace(edit_text=AsyncMock(), message_id=9001)
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=progress_msg),
        message_id=1001,
        caption=None,
        photo=[],
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(message_thread_id=None),
        message=message,
    )
    return update, progress_msg


def _mk_integration(*, use_sdk: bool):
    return SimpleNamespace(
        config=SimpleNamespace(use_sdk=use_sdk),
        sdk_manager=object() if use_sdk else None,
    )


def test_integration_supports_image_analysis_for_codex_subprocess():
    """Codex subprocess capability should be recognized as image-enabled."""
    integration = SimpleNamespace(
        config=SimpleNamespace(use_sdk=False),
        sdk_manager=None,
        process_manager=SimpleNamespace(supports_image_inputs=lambda images=None: True),
    )

    assert _integration_supports_image_analysis(integration) is True


@pytest.mark.asyncio
async def test_photo_upload_prompts_switch_to_claude_when_codex_active(tmp_path):
    """Codex active without image capability should guide user to /engine claude."""
    approved = tmp_path / "approved"
    approved.mkdir()
    user_id = 3101
    update, progress_msg = _build_update_and_progress(user_id)

    context = SimpleNamespace(
        bot_data={
            "settings": SimpleNamespace(approved_directory=approved),
            "features": _FakeFeatures(image_handler=object()),
            "cli_integrations": {
                "codex": _mk_integration(use_sdk=False),
                "claude": _mk_integration(use_sdk=True),
            },
        },
        user_data={
            "scope_state": {
                _scope_key(user_id): {
                    ENGINE_STATE_KEY: "codex",
                    "current_directory": approved,
                }
            }
        },
    )

    await handle_photo(update, context)

    rendered = progress_msg.edit_text.await_args.args[0]
    assert "当前引擎不支持图片分析" in rendered
    assert "/engine claude" in rendered
    assert "当前引擎：`codex`" in rendered


@pytest.mark.asyncio
async def test_photo_upload_reports_sdk_required_when_no_engine_supports_images(
    tmp_path,
):
    """When no integration supports images, should return SDK mode guidance."""
    approved = tmp_path / "approved"
    approved.mkdir()
    user_id = 3102
    update, progress_msg = _build_update_and_progress(user_id)

    context = SimpleNamespace(
        bot_data={
            "settings": SimpleNamespace(approved_directory=approved),
            "features": _FakeFeatures(image_handler=object()),
            "cli_integrations": {
                "claude": _mk_integration(use_sdk=False),
            },
        },
        user_data={
            "scope_state": {
                _scope_key(user_id): {
                    ENGINE_STATE_KEY: "claude",
                    "current_directory": approved,
                }
            }
        },
    )

    await handle_photo(update, context)

    rendered = progress_msg.edit_text.await_args.args[0]
    assert "图片分析需要 SDK 模式" in rendered
    assert "USE_SDK" in rendered


@pytest.mark.asyncio
async def test_photo_upload_codex_passes_cli_image_file_and_cleans_up(tmp_path):
    """Codex image flow should attach local file path and cleanup temp file."""
    approved = tmp_path / "approved"
    approved.mkdir()
    user_id = 3201

    settings = Settings(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=approved,
        use_sdk=False,
    )

    progress_msg = SimpleNamespace(
        edit_text=AsyncMock(),
        delete=AsyncMock(),
        message_id=9101,
    )
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=progress_msg),
        message_id=1001,
        caption="请分析",
        photo=[SimpleNamespace()],
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(message_thread_id=None),
        message=message,
    )

    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
    processed_image = SimpleNamespace(
        prompt="请分析",
        base64_data=base64.b64encode(image_bytes).decode("utf-8"),
        metadata={"format": "png"},
    )
    image_handler = SimpleNamespace(
        process_image=AsyncMock(return_value=processed_image)
    )

    run_command = AsyncMock(
        return_value=SimpleNamespace(
            session_id="codex-session-1",
            content="图片分析完成",
        )
    )
    codex_integration = SimpleNamespace(
        config=SimpleNamespace(use_sdk=False),
        sdk_manager=None,
        process_manager=SimpleNamespace(supports_image_inputs=lambda images=None: True),
        run_command=run_command,
    )

    context = SimpleNamespace(
        bot=SimpleNamespace(),
        bot_data={
            "settings": settings,
            "features": _FakeFeatures(image_handler=image_handler),
            "cli_integrations": {"codex": codex_integration},
        },
        user_data={
            "scope_state": {
                _scope_key(user_id): {
                    ENGINE_STATE_KEY: "codex",
                    "current_directory": approved,
                }
            }
        },
    )

    await handle_photo(update, context)

    kwargs = run_command.await_args.kwargs
    image_payload = kwargs["images"][0]
    image_path = Path(image_payload["file_path"])

    assert image_payload["media_type"] == "image/png"
    assert image_path.suffix == ".png"
    assert image_path.exists() is False
