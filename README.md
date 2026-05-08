# weup-dx-cskh

Bot CSKH tự động cho nhà sách WEUP — tích hợp Dify (AI workflow) + Make.com (automation) + Pancake (inbox/comment Facebook).

## Luồng tổng thể

```
Pancake (FB inbox/comment)
    → Make.com (debounce, routing, Data Store)
        → Dify (AI: tư vấn, chốt đơn, handoff)
    → Pancake (gửi trả lời)
```

Handoff signal: Dify append `##HANDOFF:REASON##` vào cuối response → Make detect, strip, set `handoff_state = human`.

## Cấu trúc thư mục

```
dify/
├── cskh_main.yml        # Workflow Dify đang dùng (import vào Dify)
├── cskh_accepted.yml    # Bản stable đã được duyệt
├── cskh_weup.yml        # Variant khác
└── agent_draft.yml      # Draft agent đơn giản

make/
├── scenario.json        # Export Make.com scenario (import vào Make)
└── flow_docs.md         # Tài liệu chi tiết từng node Make

kb/
├── products_full_v1.3.md   # RAG KB đầy đủ (upload lên Dify Knowledge)
├── products_combo.md        # RAG KB rút gọn chỉ có combo
├── faq.md                   # FAQ thường gặp (upload lên Dify Knowledge)
├── products_catalog.xlsx    # Bảng sản phẩm gốc có link đọc thử
└── kb_extend.xlsx           # KB mở rộng bổ sung

scripts/
├── patch_dsl.py         # Script patch dify/cskh_main.yml (thêm handoff tags)
└── workflow_draft.json  # Draft node graph (tham khảo)
```

## Dify Knowledge Base

Upload 2 file sau lên Dify KB (theo thứ tự ưu tiên):
1. `kb/products_full_v1.3.md` — thông tin sản phẩm đầy đủ
2. `kb/faq.md` — FAQ thanh toán, vận chuyển, hỗ trợ sau mua

## Make.com Data Store Schema

```json
{
  "psid": "string",
  "dify_conversation_id": "string",
  "handoff_state": "bot",
  "pending_messages": "",
  "last_message_time": 0
}
```

## Chạy patch script

```bash
python scripts/patch_dsl.py
# Tự động backup → dify/cskh_main.yml.bak
```
