#!/usr/bin/env python3
"""
从 EditThisCookie 导出的 JSON 文件中读取 Cookie，自动更新到 .env。

用法:
  1. 用浏览器扩展 EditThisCookie 导出抖音 Cookie → JSON
  2. 粘贴到 ttcookie.json
  3. 运行: python update_cookie.py
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
COOKIE_JSON = PROJECT_ROOT / "ttcookie.json"
ENV_FILE = PROJECT_ROOT / ".env"


def main():
    if not COOKIE_JSON.exists():
        print(f"[!] {COOKIE_JSON} 不存在")
        print("    请用 EditThisCookie 导出抖音 Cookie，粘贴到该文件后重试")
        return

    try:
        raw = COOKIE_JSON.read_text(encoding="utf-8").strip()
        cookies = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[!] JSON 解析失败: {e}")
        return

    # 转换为 Cookie 字符串
    pairs = []
    for c in cookies:
        name = c.get("name", "").strip()
        value = c.get("value", "").strip()
        if name and value:  # 跳过空名称的条目
            pairs.append(f"{name}={value}")

    cookie_str = "; ".join(pairs)
    print(f"[*] 已加载 {len(pairs)} 个 Cookie，总长度 {len(cookie_str)} 字符")

    # 更新 .env
    if not ENV_FILE.exists():
        print(f"[!] {ENV_FILE} 不存在")
        return

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    updated = False

    for line in lines:
        if line.startswith("DOUYIN_COOKIE="):
            new_lines.append(f"DOUYIN_COOKIE={cookie_str}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"DOUYIN_COOKIE={cookie_str}\n")

    ENV_FILE.write_text("".join(new_lines), encoding="utf-8")
    print(f"[✓] DOUYIN_COOKIE 已更新到 {ENV_FILE}")

    # 验证
    try:
        from config import DOUYIN_COOKIE
        if DOUYIN_COOKIE:
            print(f"[✓] 验证通过: .env 已正确加载新 Cookie")
        else:
            print(f"[!] 验证失败: .env 中 DOUYIN_COOKIE 为空")
    except Exception as e:
        print(f"[!] 验证异常: {e}")


if __name__ == "__main__":
    main()
