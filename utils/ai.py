"""
Lớp bọc gọi Gemini API.

Theo Section 36 của spec:
  - AI CHỈ được tạo nội dung tường thuật (mô tả khám phá, hội thoại NPC,
    không khí, sự kiện, mô tả địa điểm/Boss, văn bản thế giới).
  - AI KHÔNG được quyết định HP / damage / EXP / tiền / phần thưởng /
    kết quả chiến đấu / phong ấn / áp chế / chủ sở hữu Quỷ / bậc Quỷ / lực chiến.
    => Những giá trị đó luôn được utils/game.py tính trước, rồi mới đưa
       cho AI để "viết văn" xung quanh con số đã chốt.

Theo yêu cầu vận hành: mỗi lần gọi Gemini thành công phải được LOG lại
(chỉ trong log server, không hiển thị cho người chơi — Rule 2).
"""
import asyncio
import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, logger

_model = None
_configured = False


def _ensure_configured() -> bool:
    """Cấu hình Gemini một lần duy nhất (lazy init). Trả về False nếu thiếu key."""
    global _model, _configured
    if _configured:
        return _model is not None
    _configured = True
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY chưa được cấu hình — AI narrative sẽ dùng fallback tĩnh.")
        return False
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel(GEMINI_MODEL)
        logger.info(f"Gemini đã cấu hình xong với model '{GEMINI_MODEL}'.")
        return True
    except Exception as e:
        logger.error(f"Lỗi cấu hình Gemini: {e}")
        _model = None
        return False


async def generate_narrative(prompt: str, fallback: str, *, context: str = "generic") -> str:
    """
    Gọi Gemini để sinh văn bản tường thuật linh dị.

    prompt    : hướng dẫn nội dung (mô tả tình huống, đã kèm các con số
                đã được hệ thống chốt sẵn — AI chỉ viết văn, không tự bịa số liệu).
    fallback  : văn bản tĩnh dùng khi Gemini lỗi hoặc không có API key,
                đảm bảo gameplay không bao giờ bị chặn vì AI down.
    context   : nhãn ngắn để log biết cuộc gọi này phục vụ tính năng nào
                (vd: "khampha", "npc_dialogue", "boss_intro").
    """
    if not _ensure_configured():
        return fallback

    system_guard = (
        "Bạn là người kể chuyện cho game linh dị Discord 'Linh Dị — Thần Bí Phục Tô'. "
        "Chỉ viết văn tường thuật/mô tả không khí bằng tiếng Việt, giọng văn rùng rợn, súc tích "
        "(tối đa ~80 từ). TUYỆT ĐỐI không đề cập số liệu game (HP, damage, EXP, tiền, tỉ lệ), "
        "không nhắc đến hệ thống kỹ thuật, không tự quyết định kết quả trò chơi. "
        "Không nhắc tới việc bạn là AI, model, hay Gemini.\n\n"
    )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_model.generate_content, system_guard + prompt),
            timeout=12.0,
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ValueError("Gemini trả về nội dung rỗng.")
        # --- Log gọi thành công ---
        logger.info(f"✅ Gemini API call thành công [context={context}] ({len(text)} ký tự).")
        return text
    except asyncio.TimeoutError:
        logger.error(f"⏱️ Gemini API timeout [context={context}].")
        return fallback
    except Exception as e:
        logger.error(f"❌ Gemini API lỗi [context={context}]: {e}")
        return fallback
