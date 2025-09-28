from aiogram import types
from aiogram.utils.exceptions import MessageNotModified


async def edit_menu_text_pm(call_or_msg, text: str, reply_markup, parse_mode: str = "Markdown", disable_web_page_preview: bool = True):
    try:
        if isinstance(call_or_msg, types.CallbackQuery):
            try:
                await call_or_msg.message.edit_text(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except MessageNotModified:
                pass
            try:
                await call_or_msg.answer()
            except Exception:
                pass
        else:
            try:
                await call_or_msg.edit_text(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except MessageNotModified:
                pass
    except Exception:
        pass


async def edit_menu_text(call_or_msg, text: str, reply_markup, disable_web_page_preview: bool = True):
    return await edit_menu_text_pm(call_or_msg, text, reply_markup, parse_mode="Markdown", disable_web_page_preview=disable_web_page_preview)

