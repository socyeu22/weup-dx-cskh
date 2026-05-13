# CLAUDE.md

Behavioral guidelines + project context. Đọc kỹ trước khi làm bất cứ thứ gì.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- Transform tasks into verifiable goals before starting.
- For multi-step tasks, state a brief plan with verify steps.
- Strong success criteria let you loop independently.

---

## 5. Project Context

### Stack

| Layer | Tech |
|---|---|
| Orchestration | LangGraph + FastAPI |
| AI core | Dify (self-hosted tại `dify.weupbook.com`) |
| Webhook source | Pancake FB (`pages.fm`) |
| Debounce state | Redis |
| Long-term state | PostgreSQL |
| Vision | OpenAI o4-mini |
| Truncation | OpenAI gpt-4o |
| Deploy | Docker Compose, cùng server với Dify |

### Ground truth files

- `make/scenario.json` — flow hiện tại (Make.com), nguồn xác thực cho mọi logic
- `docs/langgraph_plan.md` — spec đầy đủ để implement LangGraph
- `docs/langgraph_migration.md` — mapping Make→LangGraph + code mẫu
- `dify/cskh_accepted.yml` — Dify workflow (**không thay đổi**)

---

## 6. Locked Decisions — Không được thay đổi nếu không có yêu cầu rõ ràng

### Dify
- Endpoint: `POST https://dify.weupbook.com/webhook/nkbCkXwlTk3v91LD/chat`
- Timeout: 300 giây
- `dify/cskh_accepted.yml` không được sửa trừ khi user yêu cầu rõ ràng

### Debounce
- Sleep = **10 giây** (`asyncio.sleep(10.0)`)
- Race check phải dùng **string comparison**: `str(last_time) != str(my_time)` — không phải số

### Handoff signal
- Parse bằng `split`, không dùng regex:
  ```python
  clean_answer = raw.split("##HANDOFF:")[0].strip()
  handoff_reason = raw.split("##HANDOFF:")[1].split("##")[0]
  ```
- `handoff_state` **KHÔNG tự chuyển sang "human"** sau handoff — bot vẫn active, chỉ notify agent

### Pancake sender_id
- Hardcoded: `"b9167563-b868-4f17-a408-ac992caa8f2b"` — không thay đổi

### Response truncation
- Ngưỡng: > 1900 ký tự → gọi gpt-4o tóm tắt về ≤ 1500 ký tự

---

## 7. Common Gotchas

- `current_message` = `data.message.original_message` (không phải `message.message`)
- `pancake_conversation_id` = `data.conversation.id` (dùng trong URL Pancake API)
- `PSID` = `data.conversation.from.id`
- Comment flow **không có debounce**, không có guard_handoff, không trigger handoff
- `dify_conversation_id` phải được lưu ngay sau Dify response đầu tiên
- FastAPI phải trả `200` ngay (`asyncio.create_task`), graph chạy background

---

## 8. Local Development

### Chạy FastAPI không cần Docker

```bash
cd langgraph/app
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Kiểm tra:
```bash
curl http://localhost:8000/health
# → {"status": "ok"}

curl -X POST http://localhost:8000/webhook/pancake \
  -H "Content-Type: application/json" \
  -d '{"page_id":"test","data":{"conversation":{"from":{"id":"psid123"},"id":"conv1","type":"INBOX"},"message":{"id":"msg1","original_message":"xin chào","attachments":[]}}}'
# → {"status": "accepted"}
```

### Chạy Redis + PostgreSQL local (Docker)

```bash
cd langgraph
docker-compose up redis postgres -d
```

Khi chạy local, sửa `.env`: dùng `localhost` thay vì tên service (`redis`, `postgres`).

### Expose localhost cho Pancake webhook

```bash
ngrok http 8000
# → https://abc123.ngrok.io
```

Trỏ webhook page test Pancake → `https://abc123.ngrok.io/webhook/pancake`.

### Test từng phase

| Phase | Cách test local |
|---|---|
| Phase 1 | `curl /health` + gửi mock payload, xem log |
| Phase 2 | `pytest` unit test store với Redis/Postgres local |
| Phase 3 | `pytest` + `respx` mock HTTP calls (Dify, Pancake, bot.base) |
| Phase 4 | `pytest` unit test từng node với mock store + mock services |
| Phase 5 | E2E với page test Pancake + ngrok |

### Chạy test

```bash
cd langgraph/app
pytest tests/ -v
```
