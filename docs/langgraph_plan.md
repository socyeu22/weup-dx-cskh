# LangGraph Implementation Plan

> Tài liệu này đủ để coding agent triển khai toàn bộ. Mọi quyết định thiết kế đã được locked. Chỉ những mục đánh `TODO` mới cần bổ sung thêm.

---

## 1. Kiến trúc

```
Pancake FB
    → bot.weupbook.com (HTTPS)
        → Nginx (reverse proxy + SSL, Certbot)
            → FastAPI + LangGraph  [port 8000 internal]
                ├── Redis          (debounce: pending_messages, last_message_time, image_cache)
                ├── PostgreSQL     (long-term: dify_conversation_id, handoff_state, pancake_conversation_id)
                └── Dify           (AI core, tại dify.weupbook.com — không thay đổi)
```

Deploy: **cùng server với Dify**, Docker Compose thêm các service app/redis/postgres/nginx.

---

## 2. Tech Stack

| Layer | Tech | Version |
|---|---|---|
| Language | Python | 3.12 |
| Web server | FastAPI + uvicorn | latest |
| Orchestration | LangGraph | latest |
| Debounce state | Redis | 7.x |
| Long-term store | PostgreSQL | 16.x |
| Reverse proxy | Nginx + Certbot | latest |
| Deployment | Docker Compose | v2 |
| Vision | OpenAI o4-mini | API |
| Truncation | OpenAI gpt-4o | API |
| HTTP client | httpx | latest (async) |

---

## 3. Project Structure

```
langgraph/
├── docker-compose.yml
├── nginx/
│   └── bot.conf
├── app/
│   ├── main.py                     # FastAPI entrypoint + webhook route
│   ├── config.py                   # env vars, constants, alert templates
│   ├── graph/
│   │   ├── state.py                # ConversationState TypedDict
│   │   ├── inbox_graph.py          # build_inbox_graph()
│   │   ├── comment_graph.py        # build_comment_graph()
│   │   └── nodes/
│   │       ├── load_state.py
│   │       ├── detect_image.py
│   │       ├── guard_handoff.py
│   │       ├── debounce.py
│   │       ├── call_dify.py
│   │       ├── parse_response.py
│   │       ├── maybe_truncate.py
│   │       ├── send_pancake.py
│   │       ├── handle_handoff.py
│   │       ├── save_state.py
│   │       └── comment/
│   │           ├── send_public_reply.py
│   │           ├── extract_lp_url.py
│   │           ├── fetch_lp.py
│   │           └── extract_book_name.py
│   ├── store/
│   │   ├── redis_store.py          # debounce ops (pending, last_time, image_cache)
│   │   └── postgres_store.py       # long-term state (dify_conv_id, handoff_state)
│   └── services/
│       ├── dify.py                 # DifyClient
│       ├── pancake.py              # PancakeClient
│       ├── bot_base.py             # BotBaseNotifier
│       └── openai_client.py        # OpenAI vision + truncation
├── migrations/
│   └── 001_init.sql
└── requirements.txt
```

---

## 4. ConversationState TypedDict

File: `app/graph/state.py`

```python
from typing import TypedDict, Literal

class ConversationState(TypedDict):
    # --- Persistent (nguồn: PostgreSQL) ---
    dify_conversation_id: str          # "" nếu conversation mới
    pancake_conversation_id: str
    handoff_state: Literal["bot", "human"]

    # --- Debounce (nguồn: Redis) ---
    pending_messages: str              # tin nhắn chờ gom, ngăn cách bởi "\n"
    last_message_time: int             # Unix timestamp (giây)

    # --- Runtime (từ webhook payload) ---
    channel: Literal["INBOX", "COMMENT"]
    page_id: str
    psid: str
    post_id: str                       # comment flow only
    message_id: str                    # comment flow only
    post_message: str                  # nội dung post FB (comment flow)
    current_message: str               # data.message.original_message
    image_url: str                     # "" nếu không có ảnh
    user_input: str                    # sau detect_image: text hoặc vision result

    # --- Runtime (set trong graph) ---
    my_time: int                       # timestamp khi vào debounce_node
    dify_raw_answer: str
    has_handoff: bool
    clean_answer: str
    handoff_reason: str                # "CONFIRM" | "COMPLAINT" | "FALLBACK" | ...
    should_stop: bool                  # True → kết thúc graph sớm

    # --- Comment flow only ---
    lp_url: str                        # URL landing page extract từ post_message
    lp_text: str                       # plain text sau khi fetch + strip HTML
    book_name: str                     # tên sách extract từ lp_text
```

---

## 5. PostgreSQL Schema

File: `migrations/001_init.sql`

```sql
CREATE TABLE IF NOT EXISTS conversation_state (
    psid                    TEXT PRIMARY KEY,
    dify_conversation_id    TEXT NOT NULL DEFAULT '',
    handoff_state           TEXT NOT NULL DEFAULT 'bot',
    pancake_conversation_id TEXT NOT NULL DEFAULT '',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 6. Redis Key Schema

| Key pattern | Kiểu | TTL | Nội dung |
|---|---|---|---|
| `cskh:{psid}:pending` | string | 1 giờ | pending_messages (multi-line) |
| `cskh:{psid}:last_time` | string | 1 giờ | Unix timestamp dạng string |
| `cskh:{psid}:image_cache` | bytes | 120 giây | raw image bytes |

---

## 7. Node Specs — Inbox Graph

Thứ tự: `load_state → detect_image → guard_handoff → debounce → call_dify → parse_response → [has_handoff?] → handle_handoff | maybe_truncate → send_pancake → save_state`

### 7.1 `load_state`

- **Input từ state**: `psid`, `pancake_conversation_id`
- **Đọc**: PostgreSQL bảng `conversation_state` WHERE psid = psid
- **Output (update state)**:
  - `dify_conversation_id` ← DB hoặc `""`
  - `handoff_state` ← DB hoặc `"bot"`
  - `pancake_conversation_id` ← DB nếu có, giữ nguyên từ webhook nếu không
- **Không có side effect nào khác**

### 7.2 `detect_image`

- **Input từ state**: `image_url`, `current_message`
- **Logic**:
  - Nếu `image_url == ""`: set `user_input = current_message`
  - Nếu có `image_url`: gọi OpenAI o4-mini vision (xem prompt §10.1) → set `user_input = vision_result`
- **Output**: `user_input`
- **Error**: nếu OpenAI fail → fallback `user_input = current_message` (không crash)

### 7.3 `guard_handoff`

- **Input từ state**: `handoff_state`, `psid`, `page_id`, `pending_messages`
- **Logic**:
  - Nếu `handoff_state == "human"`: gọi `BotBaseNotifier.notify_entry_human(state)` → set `should_stop = True`
  - Nếu `handoff_state == "bot"`: không làm gì
- **Output**: `should_stop`
- **Edge**: nếu `should_stop == True` → `END`

### 7.4 `debounce`

- **Input từ state**: `psid`, `user_input`, `pancake_conversation_id`
- **Logic** (atomic Redis pipeline):
  1. `my_time = int(time.time())`
  2. Đọc `cskh:{psid}:pending` từ Redis
  3. `new_pending = (existing_pending + "\n" + user_input).strip()`
  4. Ghi nguyên tử: `SET cskh:{psid}:pending new_pending EX 3600` + `SET cskh:{psid}:last_time str(my_time) EX 3600`
  5. `await asyncio.sleep(10.0)`
  6. Đọc lại `cskh:{psid}:last_time`
  7. **Race check**: nếu `str(refreshed_time) != str(my_time)` → set `should_stop = True`
- **Output**: `my_time`, `pending_messages` (= new_pending), `should_stop`
- **Edge**: nếu `should_stop == True` → `END`
- **Redis fail**: log CRITICAL + bỏ qua debounce (set `should_stop = False`, `pending_messages = user_input`, `my_time = int(time.time())`)

### 7.5 `call_dify`

- **Input từ state**: `pending_messages`, `dify_conversation_id`, `psid`
- **Payload**:
  ```json
  {
    "inputs": {"lp_content": "", "comment_context": ""},
    "message": "<pending_messages>",
    "user_id": "<psid>",
    "conversation_id": "<dify_conversation_id hoặc rỗng>"
  }
  ```
- **Endpoint**: `POST https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat`
- **Timeout**: 300 giây
- **Output**: `dify_raw_answer`, `dify_conversation_id` (cập nhật từ response)
- **Error handling**:
  - Retry 1 lần sau 5 giây nếu timeout hoặc HTTP 5xx
  - Nếu retry vẫn fail: reply generic error + notify agent → set `should_stop = True`
  - Generic error message: `"Dạ hệ thống đang bận, nhân viên sẽ hỗ trợ anh/chị ngay ạ 🙏"`
  - Notify agent với reason `"FALLBACK"`

### 7.6 `parse_response`

- **Input từ state**: `dify_raw_answer`
- **Logic**:
  ```python
  has_handoff = "##HANDOFF:" in raw
  if has_handoff:
      clean_answer = raw.split("##HANDOFF:")[0].strip()
      handoff_reason = raw.split("##HANDOFF:")[1].split("##")[0]
  else:
      clean_answer = raw.strip()
      handoff_reason = ""
  ```
- **Output**: `has_handoff`, `clean_answer`, `handoff_reason`
- **Edge**: `has_handoff == True` → `handle_handoff`, else → `maybe_truncate`

### 7.7 `maybe_truncate`

- **Input từ state**: `clean_answer`
- **Logic**:
  - Nếu `len(clean_answer) <= 1900`: không làm gì
  - Nếu > 1900: gọi gpt-4o tóm tắt về ≤ 1500 ký tự (xem prompt §10.3)
- **Output**: `clean_answer` (đã truncate nếu cần)
- **Error**: nếu OpenAI fail → giữ nguyên `clean_answer` (truncate thủ công 1900 ký tự cuối cùng nếu cần)

### 7.8 `send_pancake`

- **Input từ state**: `clean_answer`, `page_id`, `pancake_conversation_id`
- **API**:
  ```
  POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{pancake_conv_id}/messages
  ?page_access_token={token}

  Body: {"action": "reply_inbox", "message": "<clean_answer>", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b"}
  ```
- **page_access_token**: lookup từ `PAGE_TOKENS[page_id]` (env var)
- **Error handling**: retry tối đa 3 lần, backoff 1s → 2s → 4s. Sau đó log error, bỏ qua.
- **Output**: không thay đổi state

### 7.9 `handle_handoff`

- **Input từ state**: `psid`, `my_time`, `dify_conversation_id`, `pancake_conversation_id`, `handoff_reason`, `clean_answer`, `pending_messages`, `page_id`
- **Thứ tự thực hiện**:
  1. Lưu PostgreSQL: `UPDATE conversation_state SET handoff_state='bot', dify_conversation_id=..., pancake_conversation_id=...` — **handoff_state GIỮ NGUYÊN "bot"**
  2. Xóa Redis debounce keys (`cskh:{psid}:pending`, `cskh:{psid}:last_time`)
  3. Gửi `clean_answer` cho khách (Pancake reply_inbox — xem §7.8)
  4. Lookup `ALERT_TEMPLATES[handoff_reason]` → `template_text`
  5. Gọi `BotBaseNotifier.notify_handoff(state, template_text)`
- **Output**: không thay đổi state
- **Edge**: → `END`

### 7.10 `save_state`

- **Input từ state**: `psid`, `my_time`, `dify_conversation_id`, `pancake_conversation_id`
- **Thực hiện**:
  1. `UPDATE conversation_state SET dify_conversation_id=..., pancake_conversation_id=..., updated_at=NOW()`
  2. Xóa Redis `cskh:{psid}:pending` (clear tin nhắn đã xử lý)
  3. Cập nhật Redis `cskh:{psid}:last_time = str(my_time)` EX 3600
- **Output**: không thay đổi state
- **Edge**: → `END`

---

## 8. Node Specs — Comment Graph

Thứ tự: `load_state → send_public_reply → extract_lp_url → fetch_lp → extract_book_name → call_dify → parse_response → maybe_truncate → send_private_reply → save_state`

Không có debounce. Không có guard_handoff. Không có handle_handoff (comment flow không trigger handoff).

### 8.1 `send_public_reply`

- Gửi ngay hardcoded reply:
  ```json
  {"action": "reply_comment", "message": "a//c check inbox giúp em", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b", "message_id": "<message_id>"}
  ```
- URL: `POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{pancake_conv_id}/messages?page_access_token={token}`
- Retry logic: giống §7.8

### 8.2 `extract_lp_url`

- **Input**: `post_message` (nội dung post FB)
- Dùng OpenAI gpt-4o extract URL landing page từ text (xem prompt §10.3)
- **Output**: `lp_url: str`

### 8.3 `fetch_lp`

- GET `lp_url` với timeout 10s
- Strip HTML → plain text (dùng `html.parser` hoặc `BeautifulSoup`)
- **Output**: `lp_text: str`

### 8.4 `extract_book_name`

- Dùng OpenAI gpt-4o extract tên sách từ `lp_text` (xem prompt §10.4)
- **Output**: `book_name: str` — thêm vào state
- Nếu không extract được: `book_name = ""`

### 8.5 `call_dify` (comment variant)

- Giống §7.5 nhưng:
  - `message = f"{book_name}: {current_message}".strip(": ")` nếu có book_name, else `current_message`
  - `inputs.lp_content = lp_text` (nếu có)
  - `inputs.comment_context = post_message`

### 8.6 `send_private_reply`

```json
{"action": "private_replies", "message": "<clean_answer>", "post_id": "<post_id>", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b", "message_id": "<message_id>"}
```

---

## 9. Error Handling Rules

### Dify timeout / HTTP 5xx
1. Retry 1 lần sau 5 giây
2. Nếu vẫn fail:
   - Gửi Pancake: `"Dạ hệ thống đang bận, nhân viên sẽ hỗ trợ anh/chị ngay ạ 🙏"`
   - Gọi BotBaseNotifier với reason `"FALLBACK"`
   - Log `ERROR dify_failed psid={psid}`
   - Set `should_stop = True`

### Pancake API fail
- Retry tối đa 3 lần: delay 1s → 2s → 4s (exponential backoff)
- Sau 3 lần vẫn fail: log `ERROR pancake_failed psid={psid}`, bỏ qua

### Redis unavailable
- Log `CRITICAL redis_unavailable`
- Graceful degrade: bỏ qua debounce (set `pending_messages = user_input`, `my_time = int(time.time())`, `should_stop = False`)
- Bot tiếp tục xử lý từng tin nhắn riêng lẻ (không gom được)

### PostgreSQL unavailable
- Raise exception → FastAPI trả 500 → Pancake không retry (đã trả 200 trước đó vì background task)
- Log `CRITICAL postgres_unavailable`

### OpenAI fail (vision / truncation)
- `detect_image`: fallback về `user_input = current_message`
- `maybe_truncate`: giữ nguyên `clean_answer` (không truncate)
- `extract_book_name`: `book_name = ""`

---

## 10. Prompts

### 10.1 Vision prompt (o4-mini)

```
Bạn là AI hỗ trợ chatbot bán sách.

Nhiệm vụ:
Quan sát ảnh khách hàng gửi và suy luận khách hàng có khả năng đang muốn nhắn gì với shop.

Hãy tạo ra DUY NHẤT một câu nhắn:
* tự nhiên / ngắn gọn / giống khách hàng thật / đúng ngữ cảnh bán sách

QUAN TRỌNG:
* Nếu nhìn thấy tên sách rõ ràng thì phải đưa tên sách vào câu nhắn
* Nếu khách đang khiếu nại thì viết giống lời phàn nàn thật
* Không giải thích, không markdown, không JSON, không prefix
* Chỉ output đúng một câu
```

OpenAI Responses API:
```python
response = await openai_client.responses.create(
    model="o4-mini",
    input=[{
        "role": "user",
        "content": [
            {"type": "input_image", "image_url": image_url, "detail": "auto"},
            {"type": "input_text", "text": VISION_PROMPT},
        ],
    }],
)
result = response.output_text.strip()
```

### 10.2 Truncation prompt (gpt-4o)

```
Đây là 1 câu trả lời cho khách hàng. Hiện tại có vượt quá 1900 ký tự.
Bạn hãy tóm tắt lại nhưng vẫn đảm bảo nội dung, nhưng không vượt quá 1500 ký tự.
Nội dung tin nhắn:{clean_answer}
```

### 10.3 Extract LP URL prompt (gpt-4o)

```
Tìm URL landing page trong nội dung post Facebook dưới đây.
Chỉ trả về URL duy nhất, không kèm giải thích.
Nếu không có URL, trả về chuỗi rỗng.

Nội dung post:
{post_message}
```

### 10.4 Extract book name prompt (gpt-4o)

```
Dựa vào nội dung landing page dưới đây, trích xuất tên sách hoặc chủ đề sản phẩm đang được quảng bá.

Nội dung landing page:
{lp_text}

Yêu cầu:
- Chỉ trả về tên sách hoặc chủ đề ngắn gọn (tối đa 1 câu)
- Không kèm giá, combo, hay thông tin khác
- Ví dụ output: "THIẾT LẬP CỖ MÁY XÂY KÊNH TỰ ĐỘNG 24/24"
```

---

## 11. API Specs

### Dify

```
POST https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat
Content-Type: application/json
Timeout: 300s

Request:
{
  "inputs": {"lp_content": "", "comment_context": ""},
  "message": "<pending_messages>",
  "user_id": "<psid>",
  "conversation_id": "<dify_conversation_id>"  // "" nếu mới
}

Response:
{
  "answer": "<text, có thể kèm ##HANDOFF:REASON##>",
  "conversation_id": "<id>"
}
```

### Pancake reply_inbox

```
POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conv_id}/messages
  ?page_access_token={token}
Content-Type: application/json

{"action": "reply_inbox", "message": "...", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b"}
```

### Pancake reply_comment (public)

```json
{"action": "reply_comment", "message": "a//c check inbox giúp em", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b", "message_id": "<message_id>"}
```

### Pancake private_replies (comment)

```json
{"action": "private_replies", "message": "...", "post_id": "...", "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b", "message_id": "..."}
```

### bot.base.vn — notify agent after handoff

```
POST https://bot.base.vn/v1/webhook/send/{BOT_BASE_WEBHOOK_TOKEN}
Content-Type: application/x-www-form-urlencoded

bot_username=CSKHBOT
bot_name=cskh cảnh báo
content=[{handoff_reason}] - {template_text}
Tin nhắn gần nhất của khách: [{pending_messages}]
Xem cuội hội thoại chi tiết tại đây: https://pancake.vn/{page_id}?c_id={page_id}_{psid}
```

### bot.base.vn — notify khi khách đang ở trạng thái human

```
content=Khách hàng cần hỗ trợ trực tiếp tại: https://pancake.vn/{page_id}?c_id={page_id}_{psid}
```

---

## 12. FastAPI Entrypoint

File: `app/main.py`

```python
from fastapi import FastAPI, Request
import asyncio

app = FastAPI()

@app.post("/webhook/pancake")
async def webhook(request: Request):
    body = await request.json()
    channel = body["data"]["conversation"]["type"]  # "INBOX" | "COMMENT"

    attachments = body["data"]["message"].get("attachments", [])
    image_url = attachments[0]["url"] if attachments else ""

    initial_state = ConversationState(
        channel=channel,
        page_id=body["page_id"],
        psid=body["data"]["conversation"]["from"]["id"],
        pancake_conversation_id=body["data"]["conversation"]["id"],
        post_id=(body["data"].get("post") or {}).get("id", ""),
        message_id=body["data"]["message"]["id"],
        current_message=body["data"]["message"].get("original_message", ""),
        image_url=image_url,
        post_message=(body["data"].get("post") or {}).get("message", ""),
        # defaults
        dify_conversation_id="",
        handoff_state="bot",
        pending_messages="",
        last_message_time=0,
        user_input="",
        my_time=0,
        dify_raw_answer="",
        has_handoff=False,
        clean_answer="",
        handoff_reason="",
        should_stop=False,
        # comment flow only (default rỗng)
        lp_url="",
        lp_text="",
        book_name="",
    )

    graph = comment_graph if channel == "COMMENT" else inbox_graph
    asyncio.create_task(graph.ainvoke(initial_state))
    return {"status": "accepted"}   # trả 200 ngay, Pancake không retry

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/admin/reset/{psid}")
async def reset_handoff(psid: str):
    # Reset handoff_state về "bot" thủ công khi cần
    await postgres_store.update(psid, {"handoff_state": "bot"})
    return {"status": "ok"}
```

> **Webhook validation**: TODO — kiểm tra Pancake docs xem có gửi signature header không. Nếu có, verify trước khi xử lý.

---

## 13. Docker Compose

File: `langgraph/docker-compose.yml`

```yaml
version: "3.9"

services:
  app:
    build: ./app
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      - redis
      - postgres
    networks:
      - internal

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    networks:
      - internal

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    env_file: .env
    environment:
      POSTGRES_DB: cskh
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d
    networks:
      - internal

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/bot.conf:/etc/nginx/conf.d/default.conf
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - app
    networks:
      - internal

volumes:
  redis_data:
  postgres_data:

networks:
  internal:
```

File: `langgraph/nginx/bot.conf`

```nginx
server {
    listen 80;
    server_name bot.weupbook.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name bot.weupbook.com;

    ssl_certificate     /etc/letsencrypt/live/bot.weupbook.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.weupbook.com/privkey.pem;

    location / {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 310s;
    }
}
```

---

## 14. Environment Variables

File: `langgraph/.env` (không commit, chỉ `.env.example`)

```env
# Dify
DIFY_WEBHOOK_URL=https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat

# Pancake
PANCAKE_BASE_URL=https://pages.fm/api/public_api/v1
PANCAKE_SENDER_ID=b9167563-b868-4f17-a408-ac992caa8f2b
PAGE_TOKENS={"<page_id>": "<access_token>"}

# bot.base.vn
BOT_BASE_WEBHOOK_URL=https://bot.base.vn/v1/webhook/send/<token>

# OpenAI
OPENAI_API_KEY=sk-...

# Redis
REDIS_URL=redis://redis:6379/0

# PostgreSQL
POSTGRES_USER=cskh
POSTGRES_PASSWORD=<password>
DATABASE_URL=postgresql+asyncpg://cskh:<password>@postgres:5432/cskh

# App
# WEBHOOK_SECRET=...  # TODO: kiểm tra Pancake có gửi signature không
```

---

## 15. Config & Alert Templates

File: `app/config.py`

```python
import os, json

DIFY_WEBHOOK_URL = os.environ["DIFY_WEBHOOK_URL"]
PANCAKE_BASE_URL = os.environ["PANCAKE_BASE_URL"]
PANCAKE_SENDER_ID = os.environ["PANCAKE_SENDER_ID"]
PAGE_TOKENS: dict[str, str] = json.loads(os.environ["PAGE_TOKENS"])
BOT_BASE_WEBHOOK_URL = os.environ["BOT_BASE_WEBHOOK_URL"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
REDIS_URL = os.environ["REDIS_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]

# TODO: điền nội dung thực từ Google Sheets "Template cảnh báo"
ALERT_TEMPLATES: dict[str, str] = {
    "CONFIRM":       "TODO: nội dung template CONFIRM",
    "COMPLAINT":     "TODO: nội dung template COMPLAINT",
    "FALLBACK":      "TODO: nội dung template FALLBACK",
    "KB_MISS":       "TODO: nội dung template KB_MISS",
    "FAQ_MISS":      "TODO: nội dung template FAQ_MISS",
    "HUMAN_REQUEST": "TODO: nội dung template HUMAN_REQUEST",
}

DIFY_TIMEOUT_SECONDS = 300
DEBOUNCE_SLEEP_SECONDS = 10.0
MAX_REPLY_LENGTH = 1900
TARGET_REPLY_LENGTH = 1500
```

---

## 16. Test Scenarios

### Unit tests (mock external calls)

| Test | Input | Expected |
|---|---|---|
| `parse_response` — có handoff | `"Câu trả lời##HANDOFF:CONFIRM##"` | `has_handoff=True`, `clean_answer="Câu trả lời"`, `handoff_reason="CONFIRM"` |
| `parse_response` — không handoff | `"Câu trả lời bình thường"` | `has_handoff=False`, `clean_answer="Câu trả lời bình thường"` |
| `maybe_truncate` — ngắn | `len(clean_answer) = 100` | không gọi OpenAI |
| `maybe_truncate` — dài | `len(clean_answer) = 2000` | gọi gpt-4o, output ≤ 1500 |
| `debounce` — race check pass | `my_time == last_time` | `should_stop=False` |
| `debounce` — race check fail | `my_time != last_time` | `should_stop=True` |
| `detect_image` — không có ảnh | `image_url=""` | `user_input=current_message`, không gọi OpenAI |
| `detect_image` — có ảnh | `image_url="https://..."` | gọi o4-mini, `user_input=vision_result` |
| `guard_handoff` — human | `handoff_state="human"` | gọi `notify_entry_human`, `should_stop=True` |
| `guard_handoff` — bot | `handoff_state="bot"` | không notify, `should_stop=False` |

### Integration tests (page test, trỏ webhook về staging)

| Test | Thực hiện | Kiểm tra |
|---|---|---|
| Inbox text thường | Gửi tin nhắn text | Bot reply đúng trong 12s |
| Inbox gửi ảnh | Gửi ảnh | Bot xử lý qua o4-mini, reply đúng |
| Debounce | Gửi 3 tin liên tiếp trong 5s | Chỉ 1 lần reply, pending đã gom đủ |
| Handoff CONFIRM | Dify trả `##HANDOFF:CONFIRM##` | clean_answer gửi cho khách, agent nhận notify |
| Handoff state sau confirm | Nhắn tiếp sau CONFIRM | `handoff_state` vẫn `"bot"`, bot trả lời bình thường |
| Response dài | Dify trả > 1900 ký tự | Reply ≤ 1500 ký tự |
| Dify timeout | Mock Dify trả 504 | Reply generic error, agent notify FALLBACK |
| Comment flow | Post comment lên Facebook | Bot reply comment public "a//c check inbox", rồi private reply |
| Human state | Set `handoff_state="human"` trực tiếp DB | Nhắn tin → bot notify agent, không gọi Dify |
| Reset endpoint | POST `/admin/reset/{psid}` | `handoff_state` về `"bot"` |

---

## 17. Implementation Phases

### Phase 1 — Infrastructure
- [ ] Tạo `langgraph/` directory structure
- [ ] Viết `docker-compose.yml` (app + redis + postgres + nginx)
- [ ] Viết `nginx/bot.conf`
- [ ] Cấu hình Certbot SSL cho `bot.weupbook.com`
- [ ] FastAPI skeleton: `GET /health`, `POST /webhook/pancake` (trả 200, chưa xử lý)
- [ ] Verify webhook nhận request từ Pancake (page test)

### Phase 2 — State Layer
- [ ] `migrations/001_init.sql`
- [ ] `app/store/postgres_store.py` — `get`, `set`, `update` với asyncpg
- [ ] `app/store/redis_store.py` — atomic pipeline cho debounce, error handling graceful degrade
- [ ] `app/graph/state.py` — ConversationState TypedDict
- [ ] `app/config.py` — env vars + alert templates TODOs

### Phase 3 — Services
- [ ] `app/services/dify.py` — retry 1 lần, timeout 300s
- [ ] `app/services/pancake.py` — reply_inbox, reply_comment, private_replies; retry 3 lần backoff
- [ ] `app/services/bot_base.py` — notify_handoff, notify_entry_human
- [ ] `app/services/openai_client.py` — vision (o4-mini), truncation (gpt-4o), extract (gpt-4o)

### Phase 4 — Graph Nodes
- [ ] Inbox nodes: load_state, detect_image, guard_handoff, debounce, call_dify, parse_response, maybe_truncate, handle_handoff, send_pancake, save_state
- [ ] Comment nodes: send_public_reply, extract_lp_url, fetch_lp, extract_book_name, send_private_reply
- [ ] `inbox_graph.py` — wiring + edges
- [ ] `comment_graph.py` — wiring + edges
- [ ] Unit tests cho từng node (mock external calls)

### Phase 5 — Integration Test (page test)
- [ ] Trỏ webhook page test → `bot.weupbook.com`
- [ ] Chạy tất cả integration test scenarios (§16)

### Phase 6 — Production Cutover
- [ ] Điền ALERT_TEMPLATES thực từ Google Sheets
- [ ] Switch webhook page chính → `bot.weupbook.com`
- [ ] Monitor 24h đầu
- [ ] Tắt Make.com scenario

---

## 18. Requirements

File: `langgraph/app/requirements.txt` (versions tối thiểu, pin sau khi test)

```
fastapi
uvicorn[standard]
langgraph
httpx
redis[hiredis]
asyncpg
sqlalchemy[asyncio]
openai
python-dotenv
beautifulsoup4
```

---

## Tài liệu tham khảo

- `make/scenario.json` — ground truth của flow hiện tại
- `make/flow_docs.md` — giải thích từng node Make.com
- `docs/langgraph_migration.md` — mapping Make→LangGraph chi tiết + code mẫu
- `dify/cskh_accepted.yml` — Dify workflow (không thay đổi)
