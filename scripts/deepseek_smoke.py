from __future__ import annotations

import os

import httpx


def main() -> None:
    api_key = os.environ["LLM_API_KEY"]
    response = httpx.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
            "messages": [{"role": "user", "content": '只输出 JSON：{"ok":true}'}],
            "temperature": 0.1,
        },
        timeout=60,
    )
    print(response.status_code)
    print(response.text[:1000])


if __name__ == "__main__":
    main()
