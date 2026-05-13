# Migration Guide: Make.com → LangGraph

## Mục tiêu

Thay thế Make.com (lớp orchestration) bằng LangGraph. Dify **giữ nguyên** — vẫn là core AI xử lý intent, tư vấn, chốt đơn. LangGraph đảm nhận toàn bộ phần Make.com đang làm: nhận webhook, quản lý state, debounce, gọi Dify, gọi Pancake.

> **Nguồn xác thực:** Tài liệu này verified trực tiếp từ `make/scenario.json` (ground truth). Những điểm lấy từ `make/flow_docs.md` (thiết kế) được ghi chú rõ.

---

## 1. Kiến trúc hiện tại (Make.com)

```
Pancake FB
    → Make.com Webhook (id=1)
        → Google Sheets: lấy page_access_token (id=111)
        → Router channel (id=115)
              ├── [COMMENT] filter: type == "COMMENT"
              │       → Pancake: hardcode reply_comment "a//c check inbox" (id=62)
              │       → OpenAI: extract tên sách từ LP content (id=65, 76, 79, 77)
              │       → DataStore GetRecord by PSID (id=141)
              │       → Dify /webhook/chat (id=105 hoặc 109)
              │       → Router: response > 1900 chars? → OpenAI gpt-4o summarize
              │       → Pancake private_reply
              │
              └── [INBOX] filter: type == "INBOX"
                      → DataStore GetRecord by PSID (id=147)
                      → BasicIfElse: có attachments? (id=224)
                      │     ├── Không: dùng original_message (id=229 Placeholder)
                      │     └── Có: ParseJSON → OpenAI o4-mini vision → user_input (id=226→225)
                      → BasicMerge → user_input (id=231)
                      → Router by handoff_state (id=189)
                            ├── handoff_state == "human" → bot.base.vn notify agent (id=191)
                            └── handoff_state == "bot"
                                    → SetVariable my_time (id=148)
                                    → DataStore AddRecord: append pending + user_input (id=142)
                                    → Sleep 10s (id=150)
                                    → DataStore GetRecord (id=152)
                                    → Router race check (id=29)
                                          ├── last_message_time != my_time → STOP
                                          └── match → Dify /webhook/chat (id=91 hoặc 89)
                                                     → SetVariables: has_handoff, clean_answer, handoff_reason (id=167/171)
                                                     → Router has_handoff (id=168/172)
                                                           ├── false → Router: > 1900 chars? → summarize → Pancake reply
                                                           │          → DataStore: clear pending
                                                           └── true  → DataStore: save (handoff_state = "bot")
                                                                      → Pancake: gửi clean_answer
                                                                      → Google Sheets: lookup Template cảnh báo
                                                                      → bot.base.vn: notify agent
```

### State lưu ở đâu

| Dữ liệu | Nơi lưu |
|---|---|
| `page_access_token` | Google Sheets `Page access Token`, lookup theo `page_id` |
| `PSID → state` | Make Data Store (id=93625) |
| Template cảnh báo theo reason | Google Sheets `Template cảnh báo` (spreadsheet `1F8rjc91PaJzHL8F7Nf0NJhUlV2Uyvwb1uqj46qC481g`) |

---

## 2. Kiến trúc mục tiêu (LangGraph)

```
Pancake FB
    → FastAPI Webhook Server
        ├── [INBOX] LangGraph inbox_graph
        │         load_state → detect_image → guard_handoff → debounce
        │         → call_dify → parse_response → route_response
        │         → send_pancake + save_state
        │         (nếu has_handoff: notify_agent thay vì save pending)
        │
        └── [COMMENT] LangGraph comment_graph
                  load_state → public_reply_hardcode → call_dify
                  → parse_response → send_private_reply → save_state
                  (comment flow đơn giản hơn, không debounce)
```

Dify workflow (`dify/cskh_accepted.yml`) **không thay đổi**.

---

## 3. Webhook Payload từ Pancake

Verified từ `scenario.json`:

```json
{
  "page_id": "string",
  "event_type": "string",
  "data": {
    "conversation": {
      "from": { "id": "<PSID>" },
      "id": "<pancake_conversation_id>",
      "type": "INBOX | COMMENT"
    },
    "message": {
      "id": "<message_id>",
      "message": "<nội dung tin nhắn text>",
      "original_message": "<tin nhắn gốc, dùng trong BasicMerge>",
      "attachments": [
        {
          "url": "<image_url>",
          "type": "image"
        }
      ],
      "from": { "admin_name": "string" }
    },
    "post": {
      "id": "<post_id>",
      "message": "<nội dung post FB, dùng comment flow>"
    }
  }
}
```

- **PSID** = `data.conversation.from.id` (= `data.message.from.id`)
- **Pancake conversation ID** = `data.conversation.id` (dùng trong URL Pancake API)
- **type** viết HOA: `"INBOX"` hoặc `"COMMENT"`
- **attachments** = mảng, chỉ có khi khách gửi ảnh

---

## 4. Data Store Schema (verified từ scenario.json)

```json
{
  "key": "<PSID>",
  "handoff_state": "bot",
  "pending_messages": "",
  "last_message_time": 0,
  "dify_conversation_id": "",
  "pancake_conversation_id": "<pancake_conversation_id>"
}
```

### LangGraph State Schema

```python
from typing import TypedDict, Literal

class ConversationState(TypedDict):
    # --- Persistent (lưu Redis/DB) ---
    psid: str
    dify_conversation_id: str          # "" nếu conversation mới
    pancake_conversation_id: str       # lưu để notify agent
    handoff_state: Literal["bot", "human"]
    pending_messages: str              # tin nhắn chờ gom
    last_message_time: int             # Unix timestamp (giây)

    # --- Runtime ---
    channel: Literal["INBOX", "COMMENT"]
    page_id: str
    post_id: str                       # comment flow
    message_id: str                    # comment flow
    current_message: str               # original_message (text path)
    image_url: str                     # ảnh nếu có
    user_input: str                    # sau merge: text hoặc vision result
    my_time: int
    dify_raw_answer: str
    has_handoff: bool
    clean_answer: str
    handoff_reason: str                # CONFIRM / COMPLAINT / FALLBACK / KB_MISS / ...
    should_stop: bool
```

---

## 5. API Endpoints (Verified từ scenario.json)

### 5.1 Dify — cả inbox lẫn comment đều dùng cùng endpoint

```
POST https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat
Content-Type: application/json

{
  "inputs": {
    "lp_content": "",
    "comment_context": ""
  },
  "message": "<pending_messages (inbox) hoặc user_input (comment)>",
  "user_id": "<PSID>",
  "conversation_id": "<dify_conversation_id hoặc rỗng nếu mới>"
}
```

Response:
```json
{
  "answer": "<response, có thể kèm ##HANDOFF:REASON##>",
  "conversation_id": "<dify_conversation_id>"
}
```

> **Lưu ý**: scenario.json dùng endpoint `/webhook/nkbCkXwlTk3v91LD/chat`, không phải `/v1/chat-messages`. Khi migrate sang LangGraph nên xem xét dùng `/v1/chat-messages` (standard Dify API) để có nhiều control hơn (streaming, metadata...). Nếu giữ `/webhook/chat`, cần giữ nguyên `inputs` schema.

### 5.2 Pancake — Reply inbox (inbox flow)

```
POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{pancake_conv_id}/messages?page_access_token={token}
Content-Type: application/json

{
  "action": "reply_inbox",
  "message": "<clean_answer>",
  "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b"
}
```

### 5.3 Pancake — Reply comment (comment flow)

Public reply (hardcoded, gửi ngay khi nhận comment):
```json
{
  "action": "reply_comment",
  "message": "a//c check inbox giúp em",
  "sender_id": "b9167563-b868-4f17-a408-ac992caa8f2b",
  "message_id": "<message_id>"
}
```

Private reply (sau khi Dify xử lý):
```json
{
  "action": "private_replies",
  "message": "<clean_answer>",
  "post_id": "<post_id>",
  "sender_id": "<page_sender_id>",
  "message_id": "<message_id>"
}
```

### 5.4 bot.base.vn — Notify human agent

**Khi has_handoff == true** (sau Dify xử lý):
```
POST https://bot.base.vn/v1/webhook/send/{webhook_token}
Content-Type: application/x-www-form-urlencoded

bot_username=CSKHBOT
bot_name=cskh cảnh báo
content=[{handoff_reason}] - {template_text}
Tin nhắn gần nhất của khách: [{pending_messages}]
Xem cuội hội thoại chi tiết tại đây: https://pancake.vn/{page_id}?c_id={page_id}_{psid}
```

`template_text` = lookup từ Google Sheets `Template cảnh báo` theo `handoff_reason`.

**Khi khách đang ở trạng thái human** (handoff_state == "human" tại entry):
```
content=Khách hàng cần hỗ trợ trực tiếp tại: https://pancake.vn/{page_id}?c_id={page_id}_{psid}
```

### 5.5 Page Access Token

Lấy từ Google Sheets `Page access Token`, lookup theo `page_id`.
→ **Migration**: chuyển sang environment variables hoặc config DB:

```python
PAGE_TOKENS: dict[str, str] = {
    "<page_id>": "<access_token>",
}
```

---

## 6. Logic cốt lõi cần tái hiện

### 6.1 Image processing (INBOX only)

```python
async def detect_image_node(state: ConversationState) -> ConversationState:
    if not state.get("image_url"):
        # Không có ảnh: dùng original_message làm user_input
        return {**state, "user_input": state["current_message"]}

    # Có ảnh: gọi OpenAI o4-mini vision
    response = await openai_client.responses.create(
        model="o4-mini",
        input=[{
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": state["image_url"],
                    "detail": "auto",
                },
                {
                    "type": "input_text",
                    "text": IMAGE_VISION_PROMPT,
                }
            ],
        }],
        response_format={"type": "json_object"},
    )
    return {**state, "user_input": response.output_text.strip()}
```

**Vision prompt** (verified từ scenario.json id=225):
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

### 6.2 Guard handoff at entry (INBOX)

```python
async def guard_handoff_node(state: ConversationState, store, notifier) -> ConversationState:
    if state["handoff_state"] == "human":
        # Notify agent mà không xử lý tin nhắn
        await notifier.notify_entry_human(state)
        return {**state, "should_stop": True}
    return state
```

### 6.3 Debounce + Race condition check

Sleep = **10 giây** (verified id=150, duration=10).

```python
async def debounce_node(state: ConversationState, store) -> ConversationState:
    my_time = int(time.time())

    existing = await store.get(state["psid"])
    pending = existing.get("pending_messages", "").strip()
    new_pending = (
        (pending + "\n" + state["user_input"]).strip()
        if pending else state["user_input"]
    )

    await store.set(state["psid"], {
        **existing,
        "pending_messages": new_pending,
        "last_message_time": my_time,
        "pancake_conversation_id": state["pancake_conversation_id"],
    })

    await asyncio.sleep(10.0)

    refreshed = await store.get(state["psid"])
    if str(refreshed["last_message_time"]) != str(my_time):
        return {**state, "should_stop": True}

    return {**state, "my_time": my_time, "pending_messages": new_pending}
```

> **Race check so sánh dạng string** — verified từ scenario.json: `text:equal` chứ không phải `number:equal`.

### 6.4 Gọi Dify

```python
async def call_dify_node(state: ConversationState) -> ConversationState:
    payload = {
        "inputs": {"lp_content": "", "comment_context": ""},
        "message": state["pending_messages"] or state["user_input"],
        "user_id": state["psid"],
        "conversation_id": state["dify_conversation_id"] or "",
    }

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            "https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat",
            json=payload,
        )
    data = r.json()
    return {
        **state,
        "dify_raw_answer": data["answer"],
        "dify_conversation_id": data.get("conversation_id", state["dify_conversation_id"]),
    }
```

### 6.5 Parse response — detect + strip ##HANDOFF:##

**Công thức verified từ scenario.json** (id=167/171):

```python
def parse_response_node(state: ConversationState) -> ConversationState:
    raw = state["dify_raw_answer"]

    has_handoff = "##HANDOFF:" in raw

    if has_handoff:
        # clean_answer = phần TRƯỚC "##HANDOFF:"
        clean_answer = raw.split("##HANDOFF:")[0].strip()
        # handoff_reason = phần giữa "##HANDOFF:" và "##"
        reason_part = raw.split("##HANDOFF:")[1]  # e.g. "CONFIRM##"
        handoff_reason = reason_part.split("##")[0]  # e.g. "CONFIRM"
    else:
        clean_answer = raw.strip()
        handoff_reason = ""

    return {
        **state,
        "has_handoff": has_handoff,
        "clean_answer": clean_answer,
        "handoff_reason": handoff_reason,
    }
```

> **Lưu ý quan trọng**: Make.com dùng `split(answer, "##HANDOFF:")[1]` lấy phần ĐẦU (trước tag), không dùng regex replace. Python equivalent: `raw.split("##HANDOFF:")[0].strip()`.

**HANDOFF signals từ `dify/cskh_accepted.yml`:**

| Signal | Ý nghĩa |
|---|---|
| `CONFIRM` | Đơn xác nhận thành công |
| `COMPLAINT` | Khiếu nại / hủy đơn / đổi trả |
| `FALLBACK` | Bot không hiểu nhiều lần |
| `KB_MISS` | Không tìm thấy sản phẩm trong KB |
| `FAQ_MISS` | Câu hỏi FAQ ngoài bảng |
| `HUMAN_REQUEST` | Khách yêu cầu gặp nhân viên |

### 6.6 Response truncation (> 1900 chars)

Áp dụng khi `has_handoff == false` và response dài:

```python
async def maybe_truncate_node(state: ConversationState) -> ConversationState:
    if len(state["clean_answer"]) <= 1900:
        return state

    # Gọi GPT-4o để tóm tắt về ≤ 1500 ký tự
    prompt = (
        "Đây là 1 câu trả lời cho khách hàng. Hiện tại có vượt quá 1900 ký tự. "
        "Bạn hãy tóm tắt lại nhưng vẫn đảm bảo nội dung, nhưng không vượt quá 1500 ký tự. "
        f"Nội dung tin nhắn:{state['clean_answer']}"
    )
    response = await openai_client.responses.create(
        model="gpt-4o",
        input=[{"role": "user", "content": prompt}],
    )
    return {**state, "clean_answer": response.output_text.strip()}
```

### 6.7 Handoff — notify agent + save state

Khi `has_handoff == true`:

```python
async def handle_handoff_node(state: ConversationState, store, notifier) -> ConversationState:
    # 1. Lưu state — handoff_state GIỮ NGUYÊN "bot" (bot vẫn active)
    await store.set(state["psid"], {
        "handoff_state": "bot",
        "pending_messages": "",
        "last_message_time": state["my_time"],
        "dify_conversation_id": state["dify_conversation_id"],
        "pancake_conversation_id": state["pancake_conversation_id"],
    })

    # 2. Gửi clean_answer cho khách
    await send_pancake_reply(state)

    # 3. Lookup template + notify agent
    template = await get_alert_template(state["handoff_reason"])
    content = (
        f"[{state['handoff_reason']}] - {template}\n"
        f"Tin nhắn gần nhất của khách: [{state['pending_messages']}]\n"
        f"Xem cuội hội thoại chi tiết tại đây: https://pancake.vn/{state['page_id']}"
        f"?c_id={state['page_id']}_{state['psid']}"
    )
    await notifier.notify_bot_base(content)
    return state
```

> **Quan trọng**: `handoff_state` **không** được set thành `"human"`. Bot tiếp tục nhận tin nhắn. Agent được notify qua bot.base.vn để theo dõi. Đây là hành vi verified từ scenario.json.

### 6.8 Save state (no handoff path)

```python
async def save_state_node(state: ConversationState, store) -> ConversationState:
    await store.update(state["psid"], {
        "pending_messages": "",
        "last_message_time": state.get("my_time", 0),
        "dify_conversation_id": state["dify_conversation_id"],
        "pancake_conversation_id": state["pancake_conversation_id"],
    })
    return state
```

### 6.9 Comment flow — OpenAI steps

Comment flow dùng OpenAI cho **1 bước**: extract tên sách từ LP content.

**Public reply là hardcoded** (không dùng LLM):
```json
{
  "action": "reply_comment",
  "message": "a//c check inbox giúp em"
}
```

**OpenAI extract tên sách** (verified từ id=77, model `gpt-5.3-chat-latest` alias → thực tế gpt-4o):
```
Dựa vào nội dung landing page dưới đây, trích xuất tên sách hoặc chủ đề sản phẩm đang được quảng bá.

Nội dung landing page:
{lp_text}

Yêu cầu:
- Chỉ trả về tên sách hoặc chủ đề ngắn gọn (tối đa 1 câu)
- Không kèm giá, combo, hay thông tin khác
- Ví dụ output: "THIẾT LẬP CỖ MÁY XÂY KÊNH TỰ ĐỘNG 24/24"
```

Kết quả tên sách → ghép vào message gửi Dify, không dùng riêng cho public reply.

---

## 7. LangGraph Graph

### 7.1 Inbox graph

```python
from langgraph.graph import StateGraph, END

def build_inbox_graph():
    g = StateGraph(ConversationState)
    g.add_node("load_state",       load_state_node)
    g.add_node("detect_image",     detect_image_node)     # vision hoặc passthrough
    g.add_node("guard_handoff",    guard_handoff_node)     # if human → notify + stop
    g.add_node("debounce",         debounce_node)          # append + sleep 10s + race check
    g.add_node("call_dify",        call_dify_node)
    g.add_node("parse_response",   parse_response_node)
    g.add_node("maybe_truncate",   maybe_truncate_node)    # if > 1900 chars
    g.add_node("handle_handoff",   handle_handoff_node)    # notify agent, save bot state
    g.add_node("send_pancake",     send_pancake_node)
    g.add_node("save_state",       save_state_node)

    g.set_entry_point("load_state")
    g.add_edge("load_state",     "detect_image")
    g.add_edge("detect_image",   "guard_handoff")
    g.add_conditional_edges("guard_handoff",
        lambda s: END if s.get("should_stop") else "debounce")
    g.add_conditional_edges("debounce",
        lambda s: END if s.get("should_stop") else "call_dify")
    g.add_edge("call_dify",      "parse_response")
    g.add_conditional_edges("parse_response",
        lambda s: "handle_handoff" if s["has_handoff"] else "maybe_truncate")
    g.add_edge("handle_handoff", END)
    g.add_edge("maybe_truncate", "send_pancake")
    g.add_edge("send_pancake",   "save_state")
    g.add_edge("save_state",     END)
    return g.compile()
```

### 7.2 Comment graph

```python
def build_comment_graph():
    g = StateGraph(ConversationState)
    g.add_node("load_state",         load_state_node)
    g.add_node("send_public_reply",  send_public_reply_node)  # hardcoded "a//c check inbox"
    g.add_node("extract_lp_url",     extract_lp_url_node)     # OpenAI: tìm LP URL từ post
    g.add_node("fetch_lp",           fetch_lp_node)            # HTTP GET + strip HTML
    g.add_node("extract_book_name",  extract_book_name_node)   # OpenAI: trích tên sách
    g.add_node("call_dify",          call_dify_node)
    g.add_node("parse_response",     parse_response_node)
    g.add_node("maybe_truncate",     maybe_truncate_node)
    g.add_node("send_private_reply", send_private_reply_node)
    g.add_node("save_state",         save_state_node)

    g.set_entry_point("load_state")
    g.add_edge("load_state",          "send_public_reply")
    g.add_edge("send_public_reply",   "extract_lp_url")
    g.add_edge("extract_lp_url",      "fetch_lp")
    g.add_edge("fetch_lp",            "extract_book_name")
    g.add_edge("extract_book_name",   "call_dify")
    g.add_edge("call_dify",           "parse_response")
    g.add_conditional_edges("parse_response",
        lambda s: "handle_handoff" if s["has_handoff"] else "maybe_truncate")
    g.add_edge("maybe_truncate",      "send_private_reply")
    g.add_edge("send_private_reply",  "save_state")
    g.add_edge("save_state",          END)
    return g.compile()
```

---

## 8. Persistent State Store

### Migration từ Make Data Store

| Make Data Store | LangGraph store |
|---|---|
| `handoff_state` | Redis hash keyed by PSID |
| `pending_messages` | Cùng Redis hash |
| `last_message_time` | Cùng Redis hash |
| `dify_conversation_id` | Cùng Redis hash |
| `pancake_conversation_id` | Cùng Redis hash |
| Google Sheets `Page access Token` | Env vars hoặc config table |
| Google Sheets `Template cảnh báo` | Dict trong code hoặc DB |

### Interface tối thiểu

```python
DEFAULT_RECORD = {
    "handoff_state": "bot",
    "pending_messages": "",
    "last_message_time": 0,
    "dify_conversation_id": "",
    "pancake_conversation_id": "",
}

class StateStore:
    async def get(self, psid: str) -> dict: ...      # DEFAULT_RECORD nếu chưa có
    async def set(self, psid: str, data: dict) -> None: ...
    async def update(self, psid: str, partial: dict) -> None: ...
```

### Template cảnh báo

Hiện tại lưu ở Google Sheets `Template cảnh báo` (id: `1F8rjc91PaJzHL8F7Nf0NJhUlV2Uyvwb1uqj46qC481g`).
Lookup: filter cột A == `handoff_reason` → lấy cột đầu tiên.

Migration: hardcode dict hoặc DB table:

```python
ALERT_TEMPLATES: dict[str, str] = {
    "CONFIRM": "...",
    "COMPLAINT": "...",
    "FALLBACK": "...",
    "KB_MISS": "...",
    "FAQ_MISS": "...",
    "HUMAN_REQUEST": "...",
}
```

---

## 9. FastAPI Webhook Entrypoint

```python
from fastapi import FastAPI, Request
import asyncio

app = FastAPI()
inbox_graph   = build_inbox_graph()
comment_graph = build_comment_graph()

@app.post("/webhook/pancake")
async def webhook(request: Request):
    body = await request.json()
    is_comment = body["data"]["conversation"]["type"] == "COMMENT"

    attachments = body["data"]["message"].get("attachments", [])
    image_url = attachments[0]["url"] if attachments else ""

    initial_state: ConversationState = {
        "channel": "COMMENT" if is_comment else "INBOX",
        "page_id": body["page_id"],
        "psid": body["data"]["conversation"]["from"]["id"],
        "pancake_conversation_id": body["data"]["conversation"]["id"],
        "post_id": (body["data"].get("post") or {}).get("id", ""),
        "message_id": body["data"]["message"]["id"],
        "current_message": body["data"]["message"].get("original_message", ""),
        "image_url": image_url,
        "post_message": (body["data"].get("post") or {}).get("message", ""),
        # defaults
        "dify_conversation_id": "",
        "handoff_state": "bot",
        "pending_messages": "",
        "last_message_time": 0,
        "user_input": "",
        "should_stop": False,
        "has_handoff": False,
        "handoff_reason": "",
        "clean_answer": "",
    }

    graph = comment_graph if is_comment else inbox_graph
    asyncio.create_task(graph.ainvoke(initial_state))
    return {"status": "accepted"}

@app.post("/admin/reset/{psid}")
async def reset_handoff(psid: str):
    await store.update(psid, {"handoff_state": "bot"})
    return {"status": "ok"}
```

---

## 10. Mapping Make.com → LangGraph

| Make.com node | LangGraph | Ghi chú |
|---|---|---|
| `gateway:CustomWebHook` (id=1) | `POST /webhook/pancake` | FastAPI |
| `google-sheets:filterRows` (id=111) | `get_page_token(page_id)` | Env var / config DB |
| `builtin:BasicRouter` (id=115) | Route trong FastAPI → `inbox_graph` hoặc `comment_graph` | |
| `datastore:GetRecord` (id=147) | `load_state_node` | Đọc Redis |
| `builtin:BasicIfElse` (id=224) | `detect_image_node` | Kiểm tra `image_url` |
| `json:ParseJSON` (id=226) | Trích `url` từ attachment JSON | |
| `openai:createModelResponse` o4-mini (id=225) | `detect_image_node` với vision | |
| `placeholder:Placeholder` (id=229) | Passthrough trong `detect_image_node` | |
| `builtin:BasicMerge` (id=231) | Merge output trong `detect_image_node` → `user_input` | |
| `builtin:BasicRouter` (id=189) | `guard_handoff_node` | if human → notify + stop |
| `http:MakeRequest` bot.base.vn (id=191) | `notifier.notify_entry_human()` | Entry handoff notify |
| `util:SetVariable2` my_time (id=148) | `int(time.time())` trong `debounce_node` | |
| `datastore:AddRecord` append pending (id=142) | Trong `debounce_node` | |
| `util:FunctionSleep` 10s (id=150) | `asyncio.sleep(10.0)` | |
| `datastore:GetRecord` (id=152) | Race check read trong `debounce_node` | |
| `builtin:BasicRouter` race check (id=29) | Race check condition trong `debounce_node` | `text:equal` |
| `json:CreateJSON` (id=160) | Payload mới (conv_id="") trong `call_dify_node` | |
| `json:CreateJSON` (id=161) | Payload cũ (conv_id=existing) trong `call_dify_node` | |
| `http:MakeRequest` Dify (id=91, 89) | `call_dify_node` | POST `/webhook/nkbCkXwlTk3v91LD/chat` |
| `util:SetVariables` (id=167, 171) | `parse_response_node` | has_handoff + clean_answer + handoff_reason |
| `builtin:BasicRouter` has_handoff (id=168, 172) | Conditional edge sau `parse_response` | |
| `builtin:BasicRouter` > 1900 chars (id=202, 207) | `maybe_truncate_node` | |
| `openai:createModelResponse` gpt-4o (id=201, 209) | `maybe_truncate_node` | Tóm tắt ≤ 1500 ký tự |
| `json:CreateJSON` reply_inbox (id=135, 137) | `send_pancake_node` | |
| `http:MakeRequest` Pancake reply (id=39, 42) | `send_pancake_node` | |
| `datastore:AddRecord` clear pending (id=156, 155) | `save_state_node` | |
| `datastore:AddRecord` handoff save (id=176, 180) | `handle_handoff_node` | handoff_state = "bot" |
| `json:CreateJSON` handoff reply (id=178, 182) | `send_pancake_node` trong handoff | |
| `http:MakeRequest` Pancake handoff (id=177, 181) | Trong `handle_handoff_node` | |
| `google-sheets:filterRows` Template (id=222, 223) | `get_alert_template(reason)` | |
| `http:MakeRequest` bot.base.vn (id=183, 185) | `notifier.notify_bot_base(content)` | |
| Comment: `http:MakeRequest` reply_comment (id=62) | `send_public_reply_node` | Hardcoded text |
| Comment: `openai` extract LP URL (id=65) | `extract_lp_url_node` | |
| Comment: `http:MakeRequest` GET LP (id=76) | `fetch_lp_node` | |
| Comment: `regexp:HTMLToText` (id=79) | Strip HTML trong `fetch_lp_node` | |
| Comment: `openai` extract book name (id=77) | `extract_book_name_node` | |

---

## 11. Điểm cần lưu ý

**Dify endpoint**: `https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat` (self-hosted, không phải `api.dify.ai`). Khi migrate, cân nhắc dùng `/v1/chat-messages` để có streaming và retry dễ hơn.

**Timeout Dify**: scenario.json set `timeout=300` (5 phút). FastAPI phải return 200 ngay (`asyncio.create_task`) để Pancake không retry.

**handoff_state không tự chuyển "human"**: Bot tiếp tục xử lý sau handoff. Agent nhận notify qua bot.base.vn. Nếu muốn tắt bot sau handoff, cần thêm logic set `handoff_state = "human"` vào `handle_handoff_node`.

**clean_answer = phần TRƯỚC ##HANDOFF:****: Lấy bằng `raw.split("##HANDOFF:")[0].strip()`, không dùng regex replace.

**handoff_reason extraction**: `raw.split("##HANDOFF:")[1].split("##")[0]` → ví dụ `"CONFIRM"`.

**Race check so sánh string**: `str(last_message_time) == str(my_time)`, không so sánh số.

**Debounce dùng `user_input`**, không phải `message.message` raw. `user_input` là output của `detect_image_node` (text passthrough hoặc vision result).

**Comment flow không debounce**: Comment gửi thẳng đến Dify, không gom tin.

**Template cảnh báo**: Cần migrate từ Google Sheets sang dict hoặc DB để không phụ thuộc vào Google Sheets.

**Conversation ID**: Lưu ngay sau Dify response đầu tiên. Nếu lưu sau khi xử lý handoff, khi khách nhắn tin tiếp theo sẽ tạo conversation mới.

**sender_id** trong Pancake reply (hardcoded): `"b9167563-b868-4f17-a408-ac992caa8f2b"` — đây là page sender ID của WEUP.
