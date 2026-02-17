"""Tests for image generation fallback blocking policy."""

from types import SimpleNamespace

from src.bot.handlers.message import _enforce_no_local_image_fallback_for_image_gen


def test_enforce_no_local_image_fallback_blocks_image_gen_then_pil():
    """Should rewrite response when image-gen is followed by local PIL drawing."""
    response = SimpleNamespace(
        content="文件路径：/tmp/duck.png",
        tools_used=[
            {
                "name": "Bash",
                "command": (
                    'python3 "$HOME/.codex/skills/image-gen/scripts/image-gen.py" '
                    'generate "duck" --output "/tmp/duck.png" --ratio 1:1 --style clean'
                ),
            },
            {
                "name": "Bash",
                "command": (
                    "python3 - <<'PY'\n"
                    "from PIL import Image, ImageDraw\n"
                    "img = Image.new('RGB', (32, 32), 'yellow')\n"
                    "img.save('/tmp/duck.png')\n"
                    "PY"
                ),
            },
        ],
    )

    blocked = _enforce_no_local_image_fallback_for_image_gen(response)

    assert blocked is True
    assert "不再执行本地 PIL/Pillow 兜底绘制" in response.content


def test_enforce_no_local_image_fallback_keeps_normal_image_gen_response():
    """Should keep original response when no local PIL fallback happened."""
    response = SimpleNamespace(
        content="文件路径：/tmp/duck.png",
        tools_used=[
            {
                "name": "Bash",
                "command": (
                    'python3 "$HOME/.codex/skills/image-gen/scripts/image-gen.py" '
                    'generate "duck" --output "/tmp/duck.png"'
                ),
            }
        ],
    )

    blocked = _enforce_no_local_image_fallback_for_image_gen(response)

    assert blocked is False
    assert response.content == "文件路径：/tmp/duck.png"


def test_enforce_no_local_image_fallback_supports_nested_tool_input():
    """Should also detect fallback for tool records using input.command format."""
    response = SimpleNamespace(
        content="文件路径：/tmp/duck.png",
        tools_used=[
            {
                "name": "Bash",
                "input": {
                    "command": (
                        'python3 "$HOME/.codex/skills/image-gen/scripts/image-gen.py" '
                        'generate "duck" --output "/tmp/duck.png"'
                    )
                },
            },
            {
                "name": "Bash",
                "input": {
                    "command": (
                        "python3 - <<'PY'\n"
                        "import PIL\n"
                        "from PIL import Image\n"
                        "Image.new('RGB', (32, 32), 'yellow').save('/tmp/duck.png')\n"
                        "PY"
                    )
                },
            },
        ],
    )

    blocked = _enforce_no_local_image_fallback_for_image_gen(response)

    assert blocked is True
    assert response.content.startswith("❌ 图片生成失败")
