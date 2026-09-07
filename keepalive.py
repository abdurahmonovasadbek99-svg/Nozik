"""
Keepalive / Self-ping moduli.

Render bepul tarifi ~15 daqiqa tashqi trafik bo'lmasa xizmatni
uxlatib qo'yadi. Shu modul o'z manziliga (RENDER_EXTERNAL_URL)
muntazam so'rov yuborib, xizmatni doim "uyg'oq" ushlab turadi.

RENDER_EXTERNAL_URL Render "web service" uchun avtomatik beriladi —
qo'lda hech narsa sozlash shart emas.
"""
import logging
import requests

from config import SELF_PING_URL

logger = logging.getLogger("nozik.keepalive")


async def self_ping(context):
    """job_queue.run_repeating orqali muntazam chaqiriladi."""
    if not SELF_PING_URL:
        logger.warning("SELF_PING_URL bo'sh — RENDER_EXTERNAL_URL topilmadi, self-ping o'chirilgan.")
        return
    try:
        requests.get(SELF_PING_URL, timeout=10)
    except Exception as e:
        logger.warning(f"Self-ping muvaffaqiyatsiz: {e}")
