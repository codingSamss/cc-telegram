"""Tests for response formatting utilities."""

from unittest.mock import Mock

import pytest

from src.bot.utils.formatting import (
    CodeHighlighter,
    FormattedMessage,
    ProgressIndicator,
    ResponseFormatter,
)
from src.config.settings import Settings


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = Mock(spec=Settings)
    settings.enable_quick_actions = True
    return settings


@pytest.fixture
def formatter(mock_settings):
    """Create response formatter."""
    return ResponseFormatter(mock_settings)


class TestFormattedMessage:
    """Test FormattedMessage dataclass."""

    def test_formatted_message_creation(self):
        """Test FormattedMessage creation."""
        msg = FormattedMessage("Test message")
        assert msg.text == "Test message"
        assert msg.parse_mode == "Markdown"
        assert msg.reply_markup is None

    def test_formatted_message_length(self):
        """Test FormattedMessage length calculation."""
        msg = FormattedMessage("Hello, world!")
        assert len(msg) == 13


class TestResponseFormatter:
    """Test ResponseFormatter functionality."""

    def test_formatter_initialization(self, mock_settings):
        """Test formatter initialization."""
        formatter = ResponseFormatter(mock_settings)
        assert formatter.settings == mock_settings
        assert formatter.max_message_length == 4000
        assert formatter.max_code_block_length == 3000

    def test_format_simple_message(self, formatter):
        """Test formatting simple message."""
        text = "Hello, world!"
        messages = formatter.format_claude_response(text)

        assert len(messages) == 1
        assert messages[0].text == text
        assert messages[0].parse_mode == "Markdown"

    def test_format_code_blocks(self, formatter):
        """Test code block formatting."""
        text = "Here's some code:\n```python\nprint('hello')\n```"
        messages = formatter.format_claude_response(text)

        assert len(messages) == 1
        assert "```" in messages[0].text
        assert "# python" in messages[0].text

    def test_split_long_message(self, formatter):
        """Test splitting long messages."""
        # Create a message longer than max_message_length
        long_text = "A" * 5000
        messages = formatter.format_claude_response(long_text)

        # Should be split into multiple messages
        assert len(messages) > 1

        # Each message should be under the limit
        for msg in messages:
            assert len(msg.text) <= formatter.max_message_length

    def test_format_error_message(self, formatter):
        """Test error message formatting."""
        error_msg = formatter.format_error_message("Something went wrong", "Error")

        assert "❌" in error_msg.text
        assert "Error" in error_msg.text
        assert "Something went wrong" in error_msg.text

    def test_format_success_message(self, formatter):
        """Test success message formatting."""
        success_msg = formatter.format_success_message("Operation completed")

        assert "✅" in success_msg.text
        assert "Success" in success_msg.text
        assert "Operation completed" in success_msg.text

    def test_format_code_output(self, formatter):
        """Test code output formatting."""
        output = "Hello, world!\nThis is output."
        messages = formatter.format_code_output(output, "python", "Test Output")

        assert len(messages) >= 1
        assert "📄" in messages[0].text
        assert "Test Output" in messages[0].text
        assert "```" in messages[0].text

    def test_format_empty_code_output(self, formatter):
        """Test formatting empty code output."""
        messages = formatter.format_code_output("", "python", "Empty Output")

        assert len(messages) == 1
        assert "empty output" in messages[0].text

    def test_format_file_list(self, formatter):
        """Test file list formatting."""
        files = ["file1.py", "file2.js", "directory/"]
        msg = formatter.format_file_list(files, "test_dir")

        assert "📂" in msg.text
        assert "test_dir" in msg.text
        assert "📄 file1.py" in msg.text
        assert "📄 file2.js" in msg.text
        assert "📁 directory/" in msg.text

    def test_format_empty_file_list(self, formatter):
        """Test formatting empty file list."""
        msg = formatter.format_file_list([], "empty_dir")

        assert "📂" in msg.text
        assert "empty_dir" in msg.text
        assert "empty directory" in msg.text

    def test_format_progress_message(self, formatter):
        """Test progress message formatting."""
        msg = formatter.format_progress_message("Processing", 50.0)

        assert "🔄" in msg.text
        assert "Processing" in msg.text
        assert "50%" in msg.text
        assert "▓" in msg.text  # Progress bar

    def test_format_progress_message_no_percentage(self, formatter):
        """Test progress message without percentage."""
        msg = formatter.format_progress_message("Loading")

        assert "🔄" in msg.text
        assert "Loading" in msg.text
        assert "%" not in msg.text

    def test_clean_text(self, formatter):
        """Test text cleaning."""
        messy_text = "Hello\n\n\n\nWorld"
        cleaned = formatter._clean_text(messy_text)

        # Should reduce multiple newlines
        assert "\n\n\n" not in cleaned

    def test_markdown_escaping(self, formatter):
        """Test markdown character escaping outside code blocks."""
        text_with_markdown = "This has *bold* and _italic_ text"
        result = formatter._escape_markdown_outside_code(text_with_markdown)

        # Should escape special characters outside code
        assert r"\*" in result or r"\_" in result

    def test_code_block_preservation(self, formatter):
        """Test that code blocks preserve special characters."""
        text_with_code = "Normal text\n```\ncode_with_underscores\n```"
        result = formatter._escape_markdown_outside_code(text_with_code)

        # Code block content should not be escaped
        assert "code_with_underscores" in result

    def test_truncate_long_code_block(self, formatter):
        """Test truncation of very long code blocks."""
        long_code = "x" * 4000
        text = f"```python\n{long_code}\n```"

        messages = formatter.format_claude_response(text)

        # Should be truncated
        assert len(messages) >= 1
        assert "truncated" in messages[0].text.lower()

    def test_quick_actions_keyboard(self, formatter):
        """Test quick actions keyboard generation."""
        keyboard = formatter._get_quick_actions_keyboard()

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) > 0

        # Check that buttons have callback data
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.callback_data.startswith("quick:")

    def test_confirmation_keyboard(self, formatter):
        """Test confirmation keyboard creation."""
        keyboard = formatter.create_confirmation_keyboard("confirm:yes")

        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2

        yes_button, no_button = keyboard.inline_keyboard[0]
        assert "Yes" in yes_button.text
        assert "No" in no_button.text

    def test_navigation_keyboard(self, formatter):
        """Test navigation keyboard creation."""
        options = [
            ("Option 1", "action:1"),
            ("Option 2", "action:2"),
            ("Option 3", "action:3"),
        ]

        keyboard = formatter.create_navigation_keyboard(options)

        # Should create 2 rows (2 buttons per row, plus 1 remaining)
        assert len(keyboard.inline_keyboard) == 2
        assert len(keyboard.inline_keyboard[0]) == 2
        assert len(keyboard.inline_keyboard[1]) == 1

    def test_message_splitting_preserves_code_blocks(self, formatter):
        """Test that message splitting properly handles code blocks."""
        # Create a message with code block that would be split
        code = "x" * 2000
        text = f"Some text\n```\n{code}\n```\nMore text"

        messages = formatter._split_message(text)

        # Should properly close and reopen code blocks
        for msg in messages:
            # Count opening and closing backticks
            opening_count = msg.text.count("```\n")
            closing_count = msg.text.count("\n```")

            # Should be balanced or have one extra opening (continued in next message)
            assert abs(opening_count - closing_count) <= 1


class TestProgressIndicator:
    """Test ProgressIndicator utility functions."""

    def test_create_progress_bar(self):
        """Test progress bar creation."""
        bar = ProgressIndicator.create_bar(50, 10)

        assert len(bar) == 10
        assert "▓" in bar
        assert "░" in bar

    def test_create_progress_bar_full(self):
        """Test full progress bar."""
        bar = ProgressIndicator.create_bar(100, 10)

        assert bar == "▓" * 10

    def test_create_progress_bar_empty(self):
        """Test empty progress bar."""
        bar = ProgressIndicator.create_bar(0, 10)

        assert bar == "░" * 10

    def test_create_spinner(self):
        """Test spinner creation."""
        spinner1 = ProgressIndicator.create_spinner(0)
        spinner2 = ProgressIndicator.create_spinner(1)

        assert len(spinner1) == 1
        assert len(spinner2) == 1
        assert spinner1 != spinner2

    def test_create_dots(self):
        """Test dots indicator."""
        dots0 = ProgressIndicator.create_dots(0)
        dots1 = ProgressIndicator.create_dots(1)
        dots3 = ProgressIndicator.create_dots(3)

        assert dots0 == ""
        assert dots1 == "."
        assert dots3 == "..."


class TestCodeHighlighter:
    """Test CodeHighlighter utility functions."""

    def test_detect_language_python(self):
        """Test Python language detection."""
        lang = CodeHighlighter.detect_language("test.py")
        assert lang == "python"

    def test_detect_language_javascript(self):
        """Test JavaScript language detection."""
        lang = CodeHighlighter.detect_language("test.js")
        assert lang == "javascript"

    def test_detect_language_unknown(self):
        """Test unknown file extension."""
        lang = CodeHighlighter.detect_language("test.unknown")
        assert lang == ""

    def test_format_code_with_language(self):
        """Test code formatting with language."""
        code = "print('hello')"
        formatted = CodeHighlighter.format_code(code, "python")

        assert formatted.startswith("```python\n")
        assert formatted.endswith("\n```")
        assert code in formatted

    def test_format_code_without_language(self):
        """Test code formatting without language."""
        code = "some code"
        formatted = CodeHighlighter.format_code(code)

        assert formatted.startswith("```\n")
        assert formatted.endswith("\n```")
        assert code in formatted

    def test_format_code_with_filename(self):
        """Test code formatting with filename detection."""
        code = "console.log('hello')"
        formatted = CodeHighlighter.format_code(code, filename="test.js")

        assert "```javascript\n" in formatted

    def test_language_extensions_coverage(self):
        """Test that language extensions are properly mapped."""
        # Test a few key extensions
        assert CodeHighlighter.detect_language("test.py") == "python"
        assert CodeHighlighter.detect_language("test.js") == "javascript"
        assert CodeHighlighter.detect_language("test.ts") == "typescript"
        assert CodeHighlighter.detect_language("test.java") == "java"
        assert CodeHighlighter.detect_language("test.cpp") == "cpp"
        assert CodeHighlighter.detect_language("test.go") == "go"
        assert CodeHighlighter.detect_language("test.rs") == "rust"
