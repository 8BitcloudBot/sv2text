"""
抖音反爬参数模块
获取 msToken / ttWid 动态令牌，组合完整的反爬请求参数。
"""

import json
import random
import string
import requests
from http import cookies

DOUYIN_FINGERPRINT_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "update_version_code": "170400",
    "pc_client_type": "1",
    "pc_libra_divert": "MacIntel",
    "support_h265": "1",
    "support_dash": "1",
    "version_code": "290100",
    "version_name": "29.1.0",
    "cookie_enabled": "true",
    "screen_width": "1536",
    "screen_height": "864",
    "browser_language": "zh-CN",
    "browser_platform": "MacIntel",
    "browser_name": "Chrome",
    "browser_version": "139.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "139.0.0.0",
    "os_name": "Mac OS",
    "os_version": "10",
    "cpu_core_num": "8",
    "device_memory": "16",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "200",
}


class DouyinAntiSpam:
    MS_TOKEN_API = "https://mssdk.bytedance.com/web/common"
    MS_TOKEN_DATA = {
        "magic": 538969122,
        "version": 1,
        "dataType": 8,
        "strData": (
            "fWOdJTQR3/jwmZqBBsPO6tdNEc1jX7YTwPg0Z8CT+j3HScLFbj2Zm1XQ7/lqgSutntVKLJWaY3Hc/+vc0h+So9N1t6EqiImu5"
            "jKyUa+S4NPy6cNP0x9CUQQgb4+RRihCgsn4QyV8jivEFOsj3N5zFQbzXRyOV+9aG5B5EAnwpn8C70llsWq0zJz1VjN6y2KZiB"
            "ZRyonAHE8feSGpwMDeUTllvq6BG3AQZz7RrORLWNCLEoGzM6bMovYVPRAJipuUML4Hq/568bNb5vqAo0eOFpvTZjQFgbB7f/C"
        ),
        "tspFromClient": 0,
        "ulr": 0,
    }
    MS_TOKEN = (
        "9cguMjz4GIfQV50B_D49quM-cEyIvWMwWi0gj1bf"
        "-4YprIjt29ZrAxmDb5oIhmzEhwvcmcC4BR_kEZGmXdS1q7Ad3V94izdpXwtxgPPpozVUzQVm7KDrc5H9nfN3pLw="
    )
    TTWID_API = "https://ttwid.bytedance.com/ttwid/union/register/"
    TTWID_DATA = (
        '{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com",'
        '"migrate_info":{"ticket":"","source":"node"},"cbUrlProtocol":"https","union":true}'
    )

    def __init__(self, user_agent: str, proxy: str = None):
        self.user_agent = user_agent
        self.proxy = {"http": proxy, "https": proxy} if proxy else None
        self._ms_token: str | None = None
        self._ttwid: str | None = None

    # ─── public ──────────────────────────────────────────────────────
    def get_fingerprint_params(self) -> dict:
        return dict(DOUYIN_FINGERPRINT_PARAMS)

    def get_ms_token(self) -> str:
        if self._ms_token is None:
            self._ms_token = self._fetch_ms_token()
        return self._ms_token

    def get_ttwid(self) -> str:
        if self._ttwid is None:
            self._ttwid = self._fetch_ttwid()
        return self._ttwid

    def get_cookie_string(self, base_cookie: str) -> str:
        """组合基础 Cookie + msToken + ttWid"""
        parts = [base_cookie]
        try:
            parts.append(f"msToken={self.get_ms_token()}")
        except Exception:
            pass
        try:
            parts.append(f"ttwid={self.get_ttwid()}")
        except Exception:
            pass
        return "; ".join(parts)

    @staticmethod
    def get_fake_ms_token(size: int = 156) -> str:
        chars = string.digits + string.ascii_uppercase + string.ascii_lowercase
        return "".join(chars[random.randint(0, len(chars) - 1)] for _ in range(size))

    # ─── internal ────────────────────────────────────────────────────
    def _fetch_ms_token(self) -> str:
        headers = {"User-Agent": self.user_agent, "Content-Type": "application/json"}
        data = dict(self.MS_TOKEN_DATA)
        data["tspFromClient"] = self._timestamp_ms()
        try:
            resp = requests.post(
                self.MS_TOKEN_API,
                params={"msToken": self.MS_TOKEN},
                data=json.dumps(data),
                headers=headers,
                proxies=self.proxy,
                timeout=10,
            )
            return self._extract_from_set_cookie(resp, "msToken") or self.get_fake_ms_token()
        except Exception:
            return self.get_fake_ms_token()

    def _fetch_ttwid(self) -> str:
        headers = {"User-Agent": self.user_agent, "Content-Type": "application/json"}
        try:
            resp = requests.post(
                self.TTWID_API,
                data=self.TTWID_DATA.encode(),
                headers=headers,
                proxies=self.proxy,
                timeout=10,
            )
            return self._extract_from_set_cookie(resp, "ttwid") or ""
        except Exception:
            return ""

    @staticmethod
    def _extract_from_set_cookie(resp, key: str) -> str | None:
        if c := resp.headers.get("Set-Cookie"):
            jar = cookies.SimpleCookie()
            jar.load(c)
            if v := jar.get(key):
                return v.value
        return None

    @staticmethod
    def _timestamp_ms() -> int:
        import time
        return int(time.time() * 1000)
