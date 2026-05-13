# Migration Guide: Make.com → LangGraph

## Mục tiêu

Thay thế Make.com (lớp orchestration) bằng LangGraph. Dify **giữ nguyên** — vẫn là core AI xử lý intent, tư vấn, chốt đơn. LangGraph đảm nhận toàn bộ phần Make.com đang làm: nhận webhook, quản lý state, debounce, gọi Dify, gọi Pancake.

> **Nguồn xác thực:** Tài liệu này được verify trực tiếp từ `make/scenario.json` (ground truth) và `make/flow_docs.md` (thiết kế mở rộng). Phần nào chỉ có trong flow_docs được ghi chú rõ.

---

## 1. Kiến trúc hiện tại (Make.com)

```
Pancake FB
    → Make.com Webhook
        ├── [INBOX] Filter handoff_state != human
        │         → Debounce 4s + race check    ← thiết kế flow_docs, chưa có trong scenario.json
        │         → Dify /v1/chat-messages
        │         → Parse ##HANDOFF:REASON##
        │         → Pancake private reply
        │         → Lưu state (Google Sheets USER_INFO)
        │
        └── [COMMENT] OpenAI extract LP URL
                  → HTTP GET LP content
                  → HTMLToText strip
                  → OpenAI generate public reply
                  → Pancake public comment reply
                  → Dify /webhook/chat (private reply context)
                  → Pancake private_reply (action: private_replies)
                  → Lưu state (Google Sheets USER_INFO)
```

### State hiện tại lưu ở đâu

| Dữ liệu | Nơi lưu (Make.com) |
|---|---|
| Pancake page access token | Google Sheets sheet `Page access Token` (lookup by `page_id`) |
| PSID → dify_conversation_id | Google Sheets sheet `USER_INFO` (cols: PSID, pancake_conv_id, dify_conv_id) |
| handoff_state, pending_messages | Make Data Store (thiết kế flow_docs) |

---

## 2. Kiến trúc mục tiêu (LangGraph)

```
Pancake FB
    → FastAPI Webhook Server
        ├── [INBOX] LangGraph inbox_graph
        │         load_state → guard_handoff → debounce → call_dify
        │         → parse_response → send_pancake → save_state
        │
        └── [COMMENT] LangGraph comment_graph
                  load_state → extract_lp_url → fetch_lp → generate_public_reply
                  → send_public_reply → call_dify → parse_response
                  → send_private_reply → save_state
```

Dify workflow (`dify/cskh_accepted.yml`) **không thay đổi**.

---

## 3. Webhook Payload từ Pancake

Verified từ `scenario.json` — các field thực tế Pancake gửi:

```json
{
  "page_id": "string",
  "event_type": "string",
  "data": {
    "conversation": {
      "from": { "id": "<PSID>" },
      "id": "<pancake_conversation_id>",
      "type": "inbox | comment"
    },
    "message": {
      "id": "<message_id>",
      "message": "<nội dung tin nhắn>",
      "from": { "admin_name": "string" }
    },
    "post": {
      "id": "<post_id>",
      "message": "<nội dung post FB>"
    }
  }
}
```

Phân biệt channel: `data.conversation.type == "comment"` → comment flow, còn lại → inbox.

**PSID** = `data.conversation.from.id`
**Pancake conversation ID** = `data.conversation.id` (dùng trong Pancake API URL)

---

## 4. State Schema (LangGraph)

```python
from typing import TypedDict, Literal

class ConversationState(TypedDict):
    # --- Persistent (lưu Redis/DB) ---
    psid: str
    dify_conversation_id: str          # "" nếu conversation mới
    handoff_state: Literal["bot", "human"]
    pending_messages: str              # tin nhắn chờ gom, ngăn cách "\n"
    last_message_time: int             # Unix timestamp (giây)

    # --- Runtime (chỉ dùng trong 1 lần chạy graph) ---
    channel: Literal["inbox", "comment"]
    page_id: str
    pancake_conversation_id: str       # dùng trong Pancake API URL
    post_id: str                       # comment flow: để gửi public reply
    message_id: str                    # comment flow: để gửi private_reply
    current_message: str
    my_time: int                       # timestamp lần này để race check
    dify_raw_answer: str
    has_handoff: bool
    clean_answer: str
    lp_url: str                        # comment flow: link LP extract từ post
    lp_context: str                    # comment flow: text LP sau khi strip HTML
    public_reply_text: str             # comment flow: câu trả lời public (LLM gen)
    should_stop: bool
```

---

## 5. API Endpoints (Verified)

### 5.1 Dify

**Inbox flow** — standard chat API:
```
POST https://dify.weupbook.com/v1/chat-messages
Authorization: Bearer <DIFY_API_KEY>
Content-Type: application/json

{
  "inputs": {},
  "query": "<pending_messages hoặc current_message>",
  "response_mode": "blocking",
  "user": "<psid>",
  "conversation_id": "<dify_conversation_id>"   // bỏ qua nếu conversation mới
}
```

Response:
```json
{
  "answer": "<response text, có thể kèm ##HANDOFF:REASON##>",
  "conversation_id": "<dify_conversation_id>"
}
```

**Comment flow** — webhook endpoint (khác với inbox):
```
POST https://dify.weupbook.com/webhook/chat
Content-Type: application/json

{
  "message": "<current_message>",
  "user_id": "<psid>",
  "conversation_id": "<dify_conversation_id>"   // "" nếu mới
}
```

### 5.2 Pancake — Gửi tin nhắn vào conversation

```
POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{pancake_conversation_id}/messages?page_access_token={token}
Content-Type: application/json

{ "message": "<clean_answer>" }
```

Áp dụng cho cả inbox (private reply) và comment (private message).

### 5.3 Pancake — Comment private reply (action-based)

Comment flow dùng một format đặc biệt:
```
POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{pancake_conversation_id}/messages?page_access_token={token}
Content-Type: application/json

{
  "action": "private_replies",
  "message": "<public_reply_text>",
  "post_id": "<post_id>",
  "sender_id": "<page_sender_id>",
  "message_id": "<message_id>"
}
```

### 5.4 Page Access Token

Trong Make.com, token được lưu Google Sheets sheet `Page access Token`, lookup theo `page_id`.
→ **Migration**: chuyển sang environment variables hoặc bảng config trong DB:

```python
# Đơn giản nhất
PAGE_TOKENS: dict[str, str] = {
    "<page_id>": "<access_token>",
}

def get_page_token(page_id: str) -> str:
    return PAGE_TOKENS[page_id]
```

---

## 6. Logic cốt lõi cần tái hiện

### 6.1 Handoff guard (inbox only)

```python
def guard_handoff_node(state: ConversationState) -> ConversationState:
    if state["handoff_state"] == "human":
        return {**state, "should_stop": True}
    return state
```

`null` / record chưa tồn tại → default `"bot"` → pass.

### 6.2 Debounce + Race condition check

> Thiết kế từ `flow_docs.md`, chưa có trong `scenario.json`. Implement để tránh spam Dify khi khách nhắn nhiều tin liên tiếp.

```python
import asyncio, time

async def debounce_node(state: ConversationState, store) -> ConversationState:
    my_time = int(time.time())
    existing = await store.get(state["psid"])

    pending = existing.get("pending_messages", "").strip()
    new_pending = (
        (pending + "\n" + state["current_message"]).strip()
        if pending else state["current_message"]
    )

    await store.set(state["psid"], {
        **existing,
        "pending_messages": new_pending,
        "last_message_time": my_time,
    })

    await asyncio.sleep(4.0)

    refreshed = await store.get(state["psid"])
    if refreshed["last_message_time"] != my_time:
        return {**state, "should_stop": True}

    return {**state, "my_time": my_time, "pending_messages": new_pending}
```

### 6.3 Gọi Dify — inbox

```python
async def call_dify_inbox(state: ConversationState) -> ConversationState:
    payload = {
        "inputs": {},
        "query": state["pending_messages"] or state["current_message"],
        "response_mode": "blocking",
        "user": state["psid"],
    }
    if state["dify_conversation_id"]:
        payload["conversation_id"] = state["dify_conversation_id"]

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://dify.weupbook.com/v1/chat-messages",
            headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
            json=payload,
        )
    data = r.json()
    return {
        **state,
        "dify_raw_answer": data["answer"],
        "dify_conversation_id": data.get("conversation_id", state["dify_conversation_id"]),
    }
```

### 6.4 Parse response — detect + strip ##HANDOFF:##

```python
import re

HANDOFF_RE = re.compile(r"##HANDOFF:[A-Z_]+##")

def parse_response_node(state: ConversationState) -> ConversationState:
    raw = state["dify_raw_answer"]
    has_handoff = bool(HANDOFF_RE.search(raw))
    clean = HANDOFF_RE.sub("", raw).strip()
    return {**state, "has_handoff": has_handoff, "clean_answer": clean}
```

**Các HANDOFF signal Dify emit** (từ `dify/cskh_accepted.yml`):

| Signal | Node phát | Ý nghĩa |
|---|---|---|
| `##HANDOFF:CONFIRM##` | `confirm_llm` | Đơn xác nhận thành công |
| `##HANDOFF:COMPLAINT##` | `complaint_llm` | Khiếu nại/hủy đơn/đổi trả |
| `##HANDOFF:FALLBACK##` | `fallback_llm` | Bot không hiểu nhiều lần |
| `##HANDOFF:KB_MISS##` | `kb_miss_answer` | Không tìm thấy sản phẩm trong KB |
| `##HANDOFF:FAQ_MISS##` | `faq_llm` | Câu hỏi FAQ ngoài bảng |
| `##HANDOFF:HUMAN_REQUEST##` | `router` → `human_request_answer` | Khách yêu cầu gặp nhân viên |

### 6.5 Save state

```python
async def save_state_node(state: ConversationState, store) -> ConversationState:
    update = {
        "dify_conversation_id": state["dify_conversation_id"],
        "pending_messages": "",
        "last_message_time": state.get("my_time", 0),
        "handoff_state": "human" if state["has_handoff"] else state["handoff_state"],
    }
    await store.update(state["psid"], update)
    return state
```

### 6.6 Comment flow — OpenAI steps

Make.com dùng OpenAI cho 2 bước trong comment flow:

**Bước 1 — Extract LP URL** (từ `data.post.message`):
```python
# Prompt verified từ scenario.json
EXTRACT_LP_PROMPT = """Đọc nội dung sau:
{post_message}

Yêu cầu:
- Tìm tất cả URL có trong nội dung.
- Chỉ lấy URL liên quan đến landing page.
- Nếu có nhiều link, chọn link phù hợp nhất với ngữ cảnh landing page.

Output: JSON duy nhất {"link": "https://..."} hoặc {"link": ""} nếu không có."""
```

**Bước 2 — Generate public reply** (từ LP text sau khi strip HTML):
```python
REPLY_PROMPT = "Dựa vào nội dung landing page dưới đây và trả lời khách hàng về các combo đang có {lp_text}"
```

→ Migration: thay OpenAI bằng bất kỳ LLM nào (Gemini, Claude...) hoặc gộp 2 bước thành 1 LangGraph node.

---

## 7. LangGraph Graph

### 7.1 Inbox graph

```python
from langgraph.graph import StateGraph, END

def build_inbox_graph():
    g = StateGraph(ConversationState)
    g.add_node("load_state",     load_state_node)
    g.add_node("guard_handoff",  guard_handoff_node)
    g.add_node("debounce",       debounce_node)
    g.add_node("call_dify",      call_dify_inbox)
    g.add_node("parse_response", parse_response_node)
    g.add_node("send_pancake",   send_pancake_node)
    g.add_node("save_state",     save_state_node)

    g.set_entry_point("load_state")
    g.add_edge("load_state", "guard_handoff")
    g.add_conditional_edges("guard_handoff",
        lambda s: END if s.get("should_stop") else "debounce")
    g.add_conditional_edges("debounce",
        lambda s: END if s.get("should_stop") else "call_dify")
    g.add_edge("call_dify",      "parse_response")
    g.add_edge("parse_response", "send_pancake")
    g.add_edge("send_pancake",   "save_state")
    g.add_edge("save_state",     END)
    return g.compile()
```

### 7.2 Comment graph

```python
def build_comment_graph():
    g = StateGraph(ConversationState)
    g.add_node("load_state",          load_state_node)
    g.add_node("extract_lp_url",      extract_lp_url_node)    # OpenAI/LLM
    g.add_node("fetch_lp",            fetch_lp_node)           # HTTP GET + strip HTML
    g.add_node("generate_public",     generate_public_node)    # OpenAI/LLM
    g.add_node("send_public_reply",   send_public_reply_node)  # Pancake public comment
    g.add_node("call_dify",           call_dify_comment)       # POST /webhook/chat
    g.add_node("parse_response",      parse_response_node)
    g.add_node("send_private_reply",  send_private_reply_node) # Pancake private_replies
    g.add_node("save_state",          save_state_node)

    g.set_entry_point("load_state")
    g.add_edge("load_state",         "extract_lp_url")
    g.add_edge("extract_lp_url",     "fetch_lp")
    g.add_edge("fetch_lp",           "generate_public")
    g.add_edge("generate_public",    "send_public_reply")
    g.add_edge("send_public_reply",  "call_dify")
    g.add_edge("call_dify",          "parse_response")
    g.add_edge("parse_response",     "send_private_reply")
    g.add_edge("send_private_reply", "save_state")
    g.add_edge("save_state",         END)
    return g.compile()
```

---

## 8. Persistent State Store

### Migration từ Google Sheets

| Google Sheets (hiện tại) | LangGraph store |
|---|---|
| Sheet `USER_INFO` (PSID, pancake_conv_id, dify_conv_id) | Redis hash / PostgreSQL row keyed by PSID |
| Sheet `Page access Token` (page_id → token) | Environment variables hoặc config table |
| Make Data Store (handoff_state, pending, timestamp) | Cùng Redis hash với USER_INFO |

### Interface tối thiểu

```python
class StateStore:
    async def get(self, psid: str) -> dict: ...          # trả DEFAULT_RECORD nếu chưa có
    async def set(self, psid: str, data: dict) -> None: ...
    async def update(self, psid: str, partial: dict) -> None: ...

DEFAULT_RECORD = {
    "dify_conversation_id": "",
    "handoff_state": "bot",
    "pending_messages": "",
    "last_message_time": 0,
}
```

**Redis** là lựa chọn khuyến nghị: TTL tự dọn record cũ, async-native, latency thấp.

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
    is_comment = body["data"]["conversation"]["type"] == "comment"

    initial_state: ConversationState = {
        "channel": "comment" if is_comment else "inbox",
        "page_id": body["page_id"],
        "psid": body["data"]["conversation"]["from"]["id"],
        "pancake_conversation_id": body["data"]["conversation"]["id"],
        "post_id": body["data"]["post"]["id"],
        "message_id": body["data"]["message"]["id"],
        "current_message": body["data"]["message"]["message"],
        # post message cần cho comment flow extract LP URL
        "post_message": body["data"]["post"].get("message", ""),
        # defaults
        "dify_conversation_id": "",
        "handoff_state": "bot",
        "pending_messages": "",
        "last_message_time": 0,
        "should_stop": False,
        "has_handoff": False,
    }

    graph = comment_graph if is_comment else inbox_graph
    # Return 200 ngay, xử lý async ở background
    asyncio.create_task(graph.ainvoke(initial_state))
    return {"status": "accepted"}

# Admin endpoint — reset handoff thủ công
@app.post("/admin/reset/{psid}")
async def reset_handoff(psid: str):
    await store.update(psid, {"handoff_state": "bot"})
    return {"status": "ok"}
```

---

## 10. Mapping Make.com → LangGraph

| Make.com | LangGraph | Ghi chú |
|---|---|---|
| Webhook | `POST /webhook/pancake` | FastAPI |
| `filterRows(Page access Token)` | `get_page_token(page_id)` | Env var / config DB |
| `filterRows(USER_INFO)` | `load_state_node` | Đọc từ Redis/DB |
| `addRow(USER_INFO)` | `save_state_node` | Ghi vào Redis/DB |
| Filter `handoff_state != human` | `guard_handoff_node` | Conditional edge → END |
| Set Variable `my_time` | `int(time.time())` trong `debounce` | |
| Add/Replace record (append pending) | Trong `debounce` | |
| Sleep 4000ms | `asyncio.sleep(4.0)` trong `debounce` | |
| Router `last_message_time == my_time` | Race check trong `debounce` | |
| Router `dify_conversation_id` rỗng | `if state["dify_conversation_id"]` | Trong `call_dify` |
| `dify:makeApiCall /v1/chat-messages` | `call_dify_inbox` | Inbox |
| `http:MakeRequest /webhook/chat` | `call_dify_comment` | Comment |
| Set Variable `has_handoff / clean_answer` | `parse_response_node` | |
| Router `has_handoff == true` | Trong `save_state_node` | |
| `http:MakeRequest` Pancake reply | `send_pancake_node` | |
| `json:CreateJSON` private_replies | `send_private_reply_node` | Comment only |
| `openai (id=65)` extract LP URL | `extract_lp_url_node` | Comment only |
| `http:MakeRequest` GET LP | `fetch_lp_node` | Comment only |
| `regexp:HTMLToText` | Strip HTML trong `fetch_lp_node` | Comment only |
| `openai (id=77)` generate reply | `generate_public_node` | Comment only |

---

## 11. Điểm cần lưu ý

**Dify là self-hosted**: Endpoint `https://dify.weupbook.com` — không phải `api.dify.ai`. Cần API key của self-hosted instance.

**Hai Dify endpoint khác nhau**: Inbox dùng `/v1/chat-messages` (standard API), comment dùng `/webhook/chat`. Nên thống nhất về `/v1/chat-messages` khi migrate sang LangGraph.

**Conversation ID phải lưu ngay**: Dify trả `conversation_id` ở response đầu tiên — lưu vào store trước khi xử lý handoff (nếu không, lần sau sẽ tạo conversation mới).

**Race condition debounce**: Chấp nhận trade-off như hiện tại, hoặc dùng Redis `SET NX` / distributed lock nếu cần strict.

**Reset handoff**: Không có UI, phải gọi endpoint admin hoặc sửa trực tiếp DB.

**Timeout Dify**: Gemini 2.5 Flash có thể mất 10–30s. FastAPI phải return 200 ngay (`asyncio.create_task`) để Pancake không retry.

**Comment flow dùng OpenAI**: Có thể thay bằng bất kỳ LLM nào, kể cả Gemini (đã có trong Dify) để đồng nhất provider.
