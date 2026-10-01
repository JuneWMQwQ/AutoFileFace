# -*- coding: utf-8 -*-
"""
matcher.py — 本地登录页匹配（替代视觉模型）
用 ORB 特征匹配判断当前屏幕与某服务保存的登录页截图是否相似。
截图保存到 assets/snapshots/（项目根目录下）。
"""
import os

import cv2
import numpy as np

SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "snapshots")

_orb = None
_bf = None


def _get_matcher():
    global _orb, _bf
    if _orb is None:
        _orb = cv2.ORB_create(1200)
        _bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    return _orb, _bf


def ensure_dir() -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    return SNAPSHOT_DIR


def save_snapshot(bgr: np.ndarray, entry_id: str, index: int = 0) -> str:
    """把登录页截图保存为条目第 index 张快照，返回文件名。"""
    ensure_dir()
    path = os.path.join(SNAPSHOT_DIR, f"{entry_id}_{index}.jpg")
    cv2.imwrite(path, bgr[:, :, ::-1])  # 存 RGB
    return os.path.basename(path)


def delete_snapshots(filenames: list | None) -> None:
    if not filenames:
        return
    for fn in filenames:
        path = os.path.join(SNAPSHOT_DIR, fn)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _features(bgr: np.ndarray):
    orb, _ = _get_matcher()
    kp, des = orb.detectAndCompute(bgr, None)
    return kp, des


def similarity(screen_bgr: np.ndarray, snapshot_bgr: np.ndarray) -> float:
    """返回 0~1 匹配分数。特征匹配数占比越高越像。"""
    orb, bf = _get_matcher()
    kp1, des1 = _features(screen_bgr)
    kp2, des2 = _features(snapshot_bgr)
    if des1 is None or des2 is None:
        return 0.0
    if len(des1) < 5 or len(des2) < 5:
        return 0.0
    matches = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance] if len(matches[0]) == 2 else []
    if not good:
        return 0.0
    return min(1.0, len(good) / min(len(kp1), len(kp2)))


def load_snapshot(filename: str) -> np.ndarray | None:
    path = os.path.join(SNAPSHOT_DIR, filename)
    if not os.path.exists(path):
        return None
    rgb = cv2.imread(path)
    if rgb is None:
        return None
    return rgb[:, :, ::-1].copy()  # RGB -> BGR


def match_best(screen_bgr: np.ndarray, entries: list[dict],
               min_score: float = 0.12, top_n: int = 3) -> list[tuple[float, dict]]:
    """在当前屏幕中检索最匹配的条目（遍历每条的所有快照，取最大分）。返回 [(score, entry)] 降序。"""
    results = []
    for e in entries:
        best = 0.0
        for fn in e.get("snapshots") or []:
            snap = load_snapshot(fn)
            if snap is None:
                continue
            s = similarity(screen_bgr, snap)
            if s > best:
                best = s
        if best >= min_score:
            results.append((best, e))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_n]
