# -*- coding: utf-8 -*-
"""
vision.py — GLM-4.6V 屏幕识别 + PICUI 图床备选通道

主通道：截图 JPEG base64 直传 GLM（默认）。
备选通道：PICUI 图床（主 token → 临时 token → 上传 → URL 传给 GLM），
配置了 picui_token 且图片过大时启用。
"""
import base64
import json
import re
import time

import requests

PROMPT = """你是一个登录页面识别助手。请分析这张电脑屏幕截图，识别用户正在面对的登录场景。
请只输出一个 JSON 对象（不要 markdown 代码块，不要额外文字），格式如下：
{
  "service": "站点或应用的名称，尽量精确，如 GitHub / Steam / 公司OA / 路由器后台；无法判断填 unknown",
  "page_type": "login|register|change_password|other",
  "visible_username": "截图里已经填好的用户名（没有则为空字符串）",
  "fields": [
    {"type": "username|password|email|sms_code|other", "bbox": [x1, y1, x2, y2]}
  ],
  "page_text": "截图里主要文字的简短摘要（用于辅助匹配，20~60字）"
}
要求：
1. bbox 是相对截图宽高的比例坐标（0~1），顺序为左上右下，只有肉眼能明确看到输入框边框/提示时才列出。
2. fields 里 password 类型至多一个；如果屏幕上看不到密码框就返回空数组。
3. 中文回答 page_text。"""


class VisionClient:
    def __init__(self, api_key: str, model: str = "glm-4.6v-flash",
                 endpoint: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                 picui_token: str = "", picui_base: str = "https://v2.picui.cn"):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.picui_token = picui_token
        self.picui_base = picui_base

    # ---------- 图床（可选备选） ----------
    def _picui_temp_token(self) -> str:
        r = requests.post(
            f"{self.picui_base}/api/v1/images/tokens",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {self.picui_token}"},
            data={"num": 1, "seconds": 300}, timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("status"):
            raise RuntimeError(f"图床获取临时 token 失败: {data.get('message')}")
        return data["data"]["tokens"][0]["token"]

    def _picui_upload(self, jpeg_bytes: bytes, temp_token: str) -> tuple[str, str]:
        """上传图片，返回 (图片URL, 图片key)。"""
        r = requests.post(
            f"{self.picui_base}/api/v1/upload",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {self.picui_token}"},
            files={"file": ("screen.jpg", jpeg_bytes, "image/jpeg")},
            data={"token": temp_token, "permission": 0}, timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("status"):
            raise RuntimeError(f"图床上传失败: {data.get('message')}")
        url = data["data"]["links"]["url"]
        key = str(data["data"].get("key", ""))
        if url.startswith("http://localhost"):
            raise RuntimeError("图床返回了本地占位 URL，请检查图床配置")
        return url, key

    def _picui_delete(self, key: str) -> bool:
        """删除图床上传的图片（用完即删）。"""
        if not key:
            return False
        r = requests.delete(
            f"{self.picui_base}/api/v1/images/{key}",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {self.picui_token}"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return bool(data.get("status"))

    def _build_image(self, bgr_image):
        """构造图片输入。返回 (image_input, cleanup_fn)。
        cleanup_fn 用于用完即删图床图片；base64 通道返回 None。"""
        rgb = bgr_image[:, :, ::-1]
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=82)
        jpeg = buf.getvalue()
        if self.picui_token:
            try:
                token = self._picui_temp_token()
                url, key = self._picui_upload(jpeg, token)
                return url, (lambda: self._picui_delete(key))
            except Exception:
                # 图床失败则回退 base64
                pass
        return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"), None

    # ---------- GLM 调用 ----------
    def analyze_screen(self, bgr_image) -> dict:
        """识别截图，返回结构化 JSON dict。失败抛异常。"""
        if not self.api_key:
            raise RuntimeError("未配置视觉模型 API Key（设置页填写）")
        image_input, cleanup = self._build_image(bgr_image)
        payload = {
            "model": self.model,
            "temperature": 0.05,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_input}},
                ],
            }],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 限流/临时错误自动重试（最多 3 次，间隔递增）
        try:
            for attempt in range(3):
                resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=60)
                if resp.status_code == 200:
                    break
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"视觉模型请求失败 HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                raise RuntimeError("视觉模型请求失败（多次重试仍被限流）")
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                raise RuntimeError(f"视觉模型返回异常: {json.dumps(data, ensure_ascii=False)[:300]}")
            return _parse_json(content)
        finally:
            # 用完即删：图床图片无论识别成功/失败/异常，都在结束后立即删除
            if cleanup:
                try:
                    cleanup()
                except Exception:
                    pass  # 删除失败不阻断主流程

    def test_connection(self) -> str:
        """连通性测试：识别一张纯色小图。"""
        import numpy as np
        blank = np.zeros((64, 64, 3), dtype=np.uint8)
        blank[:, :, 0] = 180  # BGR -> 蓝
        result = self.analyze_screen(blank)
        return json.dumps(result, ensure_ascii=False)[:200]


def _parse_json(text: str) -> dict:
    """从模型输出中稳健地提取 JSON。"""
    text = text.strip()
    # 去掉 markdown 围栏
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    # 提取第一个 { ... } 块（含嵌套）
    start = text.find("{")
    if start == -1:
        raise RuntimeError("视觉模型未返回 JSON")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError("视觉模型返回的 JSON 不完整")
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        raise RuntimeError("视觉模型返回的 JSON 无法解析")
