from tawil_translate.infrastructure.openai_translator import OpenAICompatibleTranslator


class _Response:
    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"译文"}}]}'
        yield "data: [DONE]"


class _Stream:
    async def __aenter__(self):
        return _Response()

    async def __aexit__(self, *args):
        return None


class _Client:
    def __init__(self) -> None:
        self.payload = None

    def stream(self, method, url, *, json, headers):
        self.payload = json
        return _Stream()

    async def aclose(self) -> None:
        return None


async def test_deepseek_translation_disables_thinking_and_limits_output() -> None:
    translator = OpenAICompatibleTranslator(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="test",
        target_language="zh-CN",
        custom_prompt="Translate to {target_language}. Terms: {glossary}",
    )
    client = _Client()
    translator._client = client

    output = [part async for part in translator.translate("hello", context=(), glossary={})]

    assert output == ["译文"]
    assert client.payload["thinking"] == {"type": "disabled"}
    assert client.payload["max_tokens"] == 128


async def test_generic_endpoint_does_not_receive_deepseek_thinking_field() -> None:
    translator = OpenAICompatibleTranslator(
        base_url="https://example.test/v1",
        model="fast-model",
        api_key="test",
        target_language="zh-CN",
        custom_prompt="Translate to {target_language}. Terms: {glossary}",
    )
    client = _Client()
    translator._client = client

    _ = [part async for part in translator.translate("hello", context=(), glossary={})]

    assert "thinking" not in client.payload
