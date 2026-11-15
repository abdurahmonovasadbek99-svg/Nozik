"""
Keepalive / Self-ping moduli (v2).

Render bepul tarifi ~15 daqiqa TASHQI HTTP trafik bo'lmasa xizmatni uxlatadi.
Bu modul alohida oqimda (thread) o'z ommaviy manziliga (RENDER_EXTERNAL_URL)
har ~4 daqiqada so'rov yuboradi. Alohida oqim ishlatilgani uchun event loop
yoki job_queue muammo bo'lsa ham ping to'xtamaydi. Har ping logga yoziladi.
"""
import logging
import threading
import time

import requests

from config import SELF_PING_URL, SELF_PING_INTERVAL_SECONDS

logger = logging.getLogger("nozik.keepalive")


def _loop():
    time.sleep(30)
    fails = 0
    while True:
        try:
            r = requests.get(SELF_PING_URL, timeout=20)
            logger.info(f"Self-ping OK: {r.status_code}")
            fails = 0
        except Exception as e:
            fails += 1
            logger.warning(f"Self-ping xato ({fails}): {e}")
        time.sleep(min(SELF_PING_INTERVAL_SECONDS, 240) if fails == 0 else 60)


def start_self_ping():
    if not SELF_PING_URL:
        logger.warning("RENDER_EXTERNAL_URL topilmadi — self-ping ISHLAMAYDI. "
                       "Servis Web Service ekanini yoki SELF_PING_URL env berilganini tekshiring.")
        return
    threading.Thread(target=_loop, daemon=True, name="self-ping").start()
    logger.info(f"Self-ping ishga tushdi: {SELF_PING_URL}")
