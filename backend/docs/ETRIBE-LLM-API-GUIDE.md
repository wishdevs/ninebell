# Etribe-LLM API 가이드 (개발자용)

```
Base URL : http://192.168.50.2:30001
Model    : Etribe-LLM
Auth     : 없음 (api key 아무 값이나)
```
OpenAI 와 Claude(Anthropic) **둘 다** 그대로 사용 가능. (멀티모달=이미지 지원)

---

## 1) OpenAI 호환

**curl**
```bash
curl http://192.168.50.2:30001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Etribe-LLM","messages":[{"role":"user","content":"안녕"}]}'
```

**Python (openai SDK)**
```python
from openai import OpenAI
client = OpenAI(base_url="http://192.168.50.2:30001/v1", api_key="none")
r = client.chat.completions.create(
    model="Etribe-LLM",
    messages=[{"role":"user","content":"안녕"}],
)
print(r.choices[0].message.content)
```

---

## 2) Claude (Anthropic) 호환

**curl**
```bash
curl http://192.168.50.2:30001/v1/messages \
  -H 'Content-Type: application/json' -H 'anthropic-version: 2023-06-01' \
  -d '{"model":"Etribe-LLM","max_tokens":1024,"messages":[{"role":"user","content":"안녕"}]}'
```

**Python (anthropic SDK)**
```python
from anthropic import Anthropic
client = Anthropic(base_url="http://192.168.50.2:30001", api_key="none")
m = client.messages.create(
    model="Etribe-LLM",
    max_tokens=1024,
    messages=[{"role":"user","content":"안녕"}],
)
print(m.content[0].text)
```

---

## 3) 이미지(멀티모달) — OpenAI 형식

```python
r = client.chat.completions.create(
    model="Etribe-LLM",
    messages=[{"role":"user","content":[
        {"type":"text","text":"이 이미지에 뭐가 보여?"},
        {"type":"image_url","image_url":{"url":"data:image/png;base64,<BASE64>"}},
    ]}],
)
print(r.choices[0].message.content)
```
> 이미지 요청은 서버가 자동으로 thinking을 켜 정확도를 보장합니다(별도 설정 불필요).

---

## 4) 설정 (config) 안내

- **샘플링(자동 적용됨)**: `temperature=1.0`, `top_p=0.95`, `top_k=40` (모델 권장값을 프록시가 기본 주입). 직접 보내면 그 값을 우선 사용.
- **추론(thinking)**: 기본 ON(모델이 단계적으로 생각 후 답함).
  - OpenAI 응답: 최종 답은 `message.content`, 생각 과정은 별도 `reasoning_content` 채널.
  - **끄려면(OpenAI)**: 요청에 `"chat_template_kwargs": {"thinking_mode": "disabled"}` 추가 → 더 빠름. (`enabled` / `adaptive` 도 가능)
  - Claude 응답: `content` 의 text 블록에 최종 답.
- **스트리밍**: `"stream": true` (OpenAI=SSE chat.completion.chunk / Claude=SSE message_start…delta).
- **툴콜(function calling)**: OpenAI `tools`/`tool_choice`, Claude `tools` 표준 그대로 동작(parallel·streaming 포함).
- **컨텍스트 한도**: 입력+출력이 실시간 KV 풀(현재 ~400K 토큰, 대화당 최대 200K)을 넘으면 즉시 **HTTP 400** `code=context_length_exceeded` 반환.
  → 클라이언트는 이 에러를 잡아 **요약 후 새 세션으로 이어가기(handoff)** 처리할 것. (서버는 무상태)

```python
# 컨텍스트 초과 핸들링 예 (OpenAI)
try:
    r = client.chat.completions.create(model="Etribe-LLM", messages=msgs, max_tokens=2048)
except Exception as e:
    if "context_length_exceeded" in str(e):
        # 이전 대화 요약 후 새 메시지로 재시도
        ...
```

---
*동일 모델(Etribe-LLM)을 OpenAI/Claude 두 규격으로 동시에 제공. 같은 `model` 이름·같은 Base URL.*
*(8-GPU GLM-5.2 서버는 같은 규격으로 `http://172.20.50.2:30001` — 자세한 건 그 서버의 ETRIBE-LLM-API-GUIDE.md 참고. 단 GLM은 텍스트 전용, thinking 토글은 `enable_thinking`.)*
