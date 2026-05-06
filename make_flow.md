# Make Flow - CSKH Bot

## Luồng tổng thể

```mermaid
flowchart TD
    A[Webhooks] --> B[Search Token]
    B --> D{Router\ncomment vs inbox}

    %% COMMENT FLOW
    D -->|Comment| E[Lay link ladipage]
    E --> F[HTTP - Get LP content]
    F --> G[Text Parser - Trich ten sach]
    G --> H[LLM - Generate public reply\ndung LP context]
    H --> I[HTTP Pancake - Reply comment public]
    I --> J[Set Variable\ntemplate = Bao gia cho toi cuon X]
    J --> CG[Get record by PSID]
    CG --> CL{Router\ndify_conversation_id rong?}

    %% Comment - nhanh Rong
    CL -->|Rong| CL1[HTTP Dify\nkhong co conversation_id]
    CL1 --> CPV1[Set Variable\nhas_handoff / clean_answer]
    CPV1 --> CAR[Add/Replace record\nluu dify_conversation_id moi]
    CAR --> CCHO1{Router\nhas_handoff == true?}
    CCHO1 -->|Co| CCHS1[Update record\nhandoff_state = human]
    CCHS1 --> CP1[HTTP Pancake\nprivate_reply = clean_answer]
    CCHO1 -->|Khong| CP2[HTTP Pancake\nprivate_reply = clean_answer]

    %% Comment - nhanh Co
    CL -->|Co| CL2[HTTP Dify\nkem conversation_id]
    CL2 --> CPV2[Set Variable\nhas_handoff / clean_answer]
    CPV2 --> CCHO2{Router\nhas_handoff == true?}
    CCHO2 -->|Co| CCHS2[Update record\nhandoff_state = human]
    CCHS2 --> CP3[HTTP Pancake\nprivate_reply = clean_answer]
    CCHO2 -->|Khong| CP4[HTTP Pancake\nprivate_reply = clean_answer]

    %% INBOX FLOW
    D -->|Inbox| IG[Get record by PSID]
    IG --> HG[Filter\nhandoff_state != human]
    HG --> P[Set Variable\nmy_time = formatDate now X]

    P --> IAR[Add/Replace record\nappend pending_messages\nlast_message_time = my_time]
    IAR --> Q[Sleep 4000ms]
    Q --> R[Get record by PSID]
    R --> S{Router\nlast_message_time == my_time?}
    S -->|Khong khop| SSTOP([Stop])

    S -->|Khop| U{Router\ndify_conversation_id rong?}

    %% Nhanh Rong - conversation moi
    U -->|Rong| V[HTTP Dify\nkhong co conversation_id]
    V --> IPV1[Set Variable\nhas_handoff / clean_answer]
    IPV1 --> ISAVE1[Update record\ndify_conversation_id moi]
    ISAVE1 --> IHO1{Router\nhas_handoff == true?}
    IHO1 -->|Co| IHS1[Update record\nhandoff_state = human\npending_messages = rong]
    IHS1 --> IHP1[HTTP Pancake - gui clean_answer]
    IHO1 -->|Khong| INP1[HTTP Pancake - gui clean_answer]
    INP1 --> ICLR1[Update record\npending_messages = rong]

    %% Nhanh Co - conversation cu
    U -->|Co| Z[HTTP Dify\nkem conversation_id]
    Z --> IPV2[Set Variable\nhas_handoff / clean_answer]
    IPV2 --> IHO2{Router\nhas_handoff == true?}
    IHO2 -->|Co| IHS2[Update record\nhandoff_state = human\npending_messages = rong]
    IHS2 --> IHP2[HTTP Pancake - gui clean_answer]
    IHO2 -->|Khong| INP2[HTTP Pancake - gui clean_answer]
    INP2 --> ICLR2[Update record\npending_messages = rong]
```

---

## Cấu hình từng node

### Filter — chặn handoff (HG)

| Setting | Giá trị |
|---|---|
| Condition | `{{IG.handoff_state}}` not equal `human` |

Nếu fail → bundle bị drop, scenario dừng. Xử lý được cả `null` (khách mới) vì `null ≠ "human"` → pass.

---

### Set Variable — my_time (P)

| Variable | Giá trị |
|---|---|
| `my_time` | `{{formatDate(now; "X")}}` |

---

### Add/Replace record — debounce (IAR)

Overwrite: **Yes**

| Field | Giá trị |
|---|---|
| psid | từ webhook |
| dify_conversation_id | `{{IG.dify_conversation_id}}` |
| handoff_state | `{{ifempty(IG.handoff_state; "bot")}}` |
| pending_messages | `{{trim(IG.pending_messages)}}{{if(trim(IG.pending_messages); newline; "")}}{{stripTags(webhook.message)}}` |
| last_message_time | `{{my_time}}` |

> `ifempty(...; "bot")` xử lý trường hợp record chưa tồn tại — tránh lưu null vào handoff_state.

---

### Router — last_message_time == my_time? (S)

| Route | Condition | Làm gì |
|---|---|---|
| Khop | `{{R.last_message_time}}` equals `{{my_time}}` | Tiếp tục → gọi Dify |
| Khong khop | else | Stop |

---

### Router — dify_conversation_id rong? (CL, U)

| Route | Condition | Làm gì |
|---|---|---|
| Rong | `{{Get_record.dify_conversation_id}}` is empty | Gọi Dify không có conversation_id |
| Co | else | Gọi Dify kèm conversation_id |

---

### Set Variable — parse Dify response (CPV1, CPV2, IPV1, IPV2)

Đặt ngay sau mỗi HTTP Dify. HTTP module bật **Parse response: Yes**.

| Variable | Giá trị |
|---|---|
| `has_handoff` | `{{if(contains(HTTP_Dify.data.answer; "##HANDOFF:"); true; false)}}` |
| `clean_answer` | `{{trim(replace(HTTP_Dify.data.answer; /##HANDOFF:[A-Z_]+##/; ""))}}` |

---

### Add/Replace record — lưu dify_conversation_id mới (CAR, comment Rong)

Overwrite: **Yes**

| Field | Giá trị |
|---|---|
| psid | từ webhook |
| dify_conversation_id | `{{CL1.data.conversation_id}}` |
| handoff_state | `{{ifempty(CG.handoff_state; "bot")}}` |
| pending_messages | `{{CG.pending_messages}}` |
| last_message_time | `{{CG.last_message_time}}` |

> Add/Replace vì record có thể chưa tồn tại (khách comment lần đầu). Map lại tất cả fields để tránh mất dữ liệu inbox.

---

### Update record — lưu dify_conversation_id mới (ISAVE1, inbox Rong)

| Field | Giá trị |
|---|---|
| psid | từ webhook *(key)* |
| dify_conversation_id | `{{V.data.conversation_id}}` |

> Update được vì IAR đã tạo record trước đó.

---

### Router — has_handoff == true? (CCHO1, CCHO2, IHO1, IHO2)

| Route | Condition | Làm gì |
|---|---|---|
| Co handoff | `{{has_handoff}}` equals `true` | Xử lý handoff |
| Khong | else | Gửi Pancake, xoá pending |

---

### Update record — set handoff_state = human (CCHS1, CCHS2, IHS1, IHS2)

| Field | Giá trị |
|---|---|
| psid | từ webhook *(key)* |
| handoff_state | `human` |
| pending_messages | *(để trống)* |

---

### Update record — xoá pending_messages (ICLR1, ICLR2)

| Field | Giá trị |
|---|---|
| psid | từ webhook *(key)* |
| pending_messages | *(để trống)* |

---

## Data Store Schema

```json
{
  "psid": "string",
  "dify_conversation_id": "string",
  "handoff_state": "bot",
  "pending_messages": "",
  "last_message_time": 0
}
```

---

## Ghi chú

- **Get record — if not found: Continue**: checkbox trong Make module setting — trả về null thay vì Stop; flow chạy bình thường, record được tạo bởi Add/Replace phía sau
- **ifempty(handoff_state; "bot")**: tránh lưu null khi record mới tạo lần đầu
- **HTTP Parse response: Yes**: không cần node JSON Parse riêng — truy cập thẳng `HTTP_Dify.data.answer`, `HTTP_Dify.data.conversation_id`
- **Set Variable sau HTTP Dify**: tập trung detect + strip `##HANDOFF:REASON##` tại 1 chỗ — Router và Pancake chỉ đọc `has_handoff` và `clean_answer`
- **clean_answer luôn dùng được**: nếu không có tag, `replace()` trả về text gốc — cả 2 nhánh Router gửi `clean_answer` cho Pancake
- **Add/Replace vs Update**: Add/Replace cho record có thể chưa tồn tại (CAR, IAR); Update cho record chắc chắn đã tồn tại (ISAVE1, IHS, ICLR, CCHS)
- **ISAVE1**: lưu dify_conversation_id mới trước Router handoff — đảm bảo conversation_id được lưu bất kể handoff hay không
- **Debounce 4000ms**: gom tin nhắn liên tiếp thành 1 request Dify
- **Race condition**: chấp nhận rủi ro thấp khi 2 tin nhắn đến trong vài chục ms — Make Data Store không hỗ trợ atomic append
- **Human handoff signal**: Dify append `##HANDOFF:REASON##` vào cuối response (CONFIRM / COMPLAINT / FALLBACK / KB_MISS / FAQ_MISS / HUMAN_REQUEST) — Make detect bằng `contains "##HANDOFF:"`, strip bằng regex `/##HANDOFF:[A-Z_]+##/`, gửi `clean_answer` cho khách
- **handoff_state check**: dùng Filter thay vì Router — chỉ cần gate "đi tiếp hoặc dừng", không có nhánh thứ 2; null cũng pass vì null ≠ "human"
- **Các trường hợp handoff từ Dify**: CONFIRM (luôn), COMPLAINT (luôn), FALLBACK (luôn), INQUIRY khi KB rỗng, FAQ khi câu hỏi ngoài bảng, HUMAN_REQUEST (khách xin gặp nhân viên)
