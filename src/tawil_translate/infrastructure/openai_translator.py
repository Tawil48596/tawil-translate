from __future__ import annotations

import json
from collections.abc import AsyncIterator


class OpenAICompatibleTranslator:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        target_language: str,
        custom_prompt: str,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key:
            raise ValueError("translation API key is empty")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.target_language = target_language
        self.custom_prompt = custom_prompt
        self.timeout_seconds = timeout_seconds

    async def translate(
        self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
    ) -> AsyncIterator[str]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError('install desktop dependencies: pip install -e ".[desktop]"') from exc
        glossary_text = ", ".join(f"{source}={target}" for source, target in glossary.items())
        recent = "\n".join(context[-4:])
        system = self.custom_prompt.replace("{target_language}", self.target_language).replace(
            "{glossary}", glossary_text or "无"
        )
        user = f"Recent context:\n{recent}\n\nCurrent utterance:\n{text}" if recent else text
        payload = {
            "model": self.model,
            "stream": True,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(self.timeout_seconds, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
            "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data = json.loads(line[6:])
                delta = data["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    yield delta
