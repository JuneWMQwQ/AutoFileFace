# -*- coding: utf-8 -*-
"""
screen.py — 屏幕捕获与坐标映射
- 截图：mss（物理像素），取鼠标所在显示器
- DPI：进程级 Per-Monitor DPI Aware，保证截图与鼠标坐标一致
"""
import ctypes
import io

import mss
import numpy as np
from PIL import Image


def set_dpi_awareness() -> None:
    """将本进程设为按显示器 DPI 感知，避免坐标偏移。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_cursor_monitor() -> dict:
    """返回鼠标所在显示器的 mss 监控信息。"""
    with mss.mss() as sct:
        cursor = sct.monitors[0]  # 虚拟屏幕边界
        try:
            import ctypes.wintypes
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cx, cy = pt.x, pt.y
        except Exception:
            cx, cy = cursor["width"] // 2, cursor["height"] // 2
        # 找到包含光标的显示器
        best = None
        for m in sct.monitors[1:]:
            if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
                best = m
                break
        return best or cursor


def capture_bgr(max_width: int = 1280) -> tuple[np.ndarray, dict]:
    """截取鼠标所在显示器画面，返回 (BGR ndarray, 显示器信息)。"""
    monitor = get_cursor_monitor()
    with mss.mss() as sct:
        shot = sct.grab(monitor)
    img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
    # 限制宽度，保持比例（视觉模型输入用）
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    bgr = np.array(img)[:, :, ::-1].copy()  # RGB -> BGR
    return bgr, monitor


def compress_jpeg_base64(bgr: np.ndarray, quality: int = 82) -> str:
    """BGR 图 → JPEG → base64（供视觉模型）。"""
    rgb = bgr[:, :, ::-1]
    img = Image.fromarray(rgb)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    import base64
    return base64.b64encode(buf.getvalue()).decode("ascii")


def bbox_ratio_to_screen(monitor: dict, bbox: list) -> tuple[int, int, int, int]:
    """把归一化 bbox [x1,y1,x2,y2]（0~1）换算成屏幕物理坐标。"""
    x1, y1, x2, y2 = bbox
    left = monitor["left"] + int(x1 * monitor["width"])
    top = monitor["top"] + int(y1 * monitor["height"])
    right = monitor["left"] + int(x2 * monitor["width"])
    bottom = monitor["top"] + int(y2 * monitor["height"])
    return left, top, right, bottom
