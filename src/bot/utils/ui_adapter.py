"""Bot UI adapter helpers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

KeyboardSpec = list[list[tuple[str, str]]]


def build_reply_markup_from_spec(
    keyboard_spec: KeyboardSpec | None,
) -> InlineKeyboardMarkup | None:
    """Build telegram inline keyboard markup from tuple-based keyboard spec."""
    if not keyboard_spec:
        return None

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text, callback_data=data) for text, data in row]
            for row in keyboard_spec
        ]
    )
