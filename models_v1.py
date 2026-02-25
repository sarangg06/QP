import json
import os
import time
from urllib import request, error


class LMStudioClient:
    def __init__(self, base_url: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LM Studio HTTP error {e.code}: {detail}") from e
        except Exception as e:
            raise RuntimeError(f"LM Studio request failed: {e}") from e

        try:
            parsed = json.loads(body)
            return parsed["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Unexpected LM Studio response: {body}") from e

    def reset(self):
        return None

    def close(self):
        return None


LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_SQL_MODEL = os.getenv("LMSTUDIO_SQL_MODEL", "microsoft/phi-4-mini-reasoning")
LMSTUDIO_RESPONSE_MODEL = os.getenv("LMSTUDIO_RESPONSE_MODEL", "microsoft/phi-4-mini-reasoning")


def load_sql_model():
    time.sleep(0.2)
    print(f"SQL model client ready (LM Studio): base_url={LMSTUDIO_BASE_URL}, model='{LMSTUDIO_SQL_MODEL}'")
    return LMStudioClient(base_url=LMSTUDIO_BASE_URL, model=LMSTUDIO_SQL_MODEL)


def load_response_model():
    time.sleep(0.2)
    print(f"Response model client ready (LM Studio): base_url={LMSTUDIO_BASE_URL}, model='{LMSTUDIO_RESPONSE_MODEL}'")
    return LMStudioClient(base_url=LMSTUDIO_BASE_URL, model=LMSTUDIO_RESPONSE_MODEL)
