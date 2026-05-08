{
  "nodes" [
    {
      "id": "start",
      "type": "start",
      "data": {}
    },
    {
      "id": "user_input",
      "type": "input",
      "data": {
        "variable": "user_query"
      }
    },
    {
      "id": "llm_preprocess",
      "type": "llm",
      "data": {
        "model": "gpt-4o",
        "prompt": "Phân tích câu người dùng và trả về JSON duy nhất:\n\n{\n  \"stage\": \"IB_TRIGGER | INTEREST | INQUIRY | ASK_PRICE | BUY_INTENT | ORDER_INFO | CONFIRM | COMPLAINT\",\n  \"intent\": \"...\",\n  \"entities\": {\n    \"product\": \"...\",\n    \"name\": \"...\",\n    \"phone\": \"...\",\n    \"address\": \"...\"\n  },\n  \"order_state\": {\n    \"has_name\": true/false,\n    \"has_phone\": true/false,\n    \"has_address\": true/false\n  }\n}\n\nChỉ trả JSON, không giải thích.\nInput: {{user_query}}"
      }
    },
    {
      "id": "parse_json",
      "type": "code",
      "data": {
        "code": "import json\n\ndef main(arg1):\n    try:\n        cleaned = arg1.replace(\"\\xa0\", \" \")\n        data = json.loads(cleaned)\n    except:\n        data = {}\n\n    return {\n        \"stage\": data.get(\"stage\"),\n        \"intent\": data.get(\"intent\"),\n        \"product\": data.get(\"entities\", {}).get(\"product\"),\n        \"name\": data.get(\"entities\", {}).get(\"name\"),\n        \"phone\": data.get(\"entities\", {}).get(\"phone\"),\n        \"address\": data.get(\"entities\", {}).get(\"address\"),\n        \"has_name\": data.get(\"order_state\", {}).get(\"has_name\"),\n        \"has_phone\": data.get(\"order_state\", {}).get(\"has_phone\"),\n        \"has_address\": data.get(\"order_state\", {}).get(\"has_address\")\n    }"
      }
    },
    {
      "id": "router",
      "type": "if",
      "data": {
        "conditions": [
          {
            "if": "{{stage}} == 'BUY_INTENT'",
            "goto": "order_request"
          },
          {
            "if": "{{stage}} == 'ORDER_INFO'",
            "goto": "order_check"
          },
          {
            "if": "{{stage}} == 'CONFIRM'",
            "goto": "order_done"
          },
          {
            "if": "{{stage}} == 'INQUIRY'",
            "goto": "consult"
          }
        ],
        "else": "fallback"
      }
    },

    // ===== ORDER FLOW =====

    {
      "id": "order_request",
      "type": "answer",
      "data": {
        "text": "Dạ em chốt đơn cho mình luôn nhé ❤️\n\nAnh/chị gửi giúp em:\n- Tên người nhận\n- SĐT\n- Địa chỉ\n\nEm lên đơn ngay ạ 📦"
      }
    },

    {
      "id": "order_check",
      "type": "if",
      "data": {
        "conditions": [
          {
            "if": "{{has_name}} == false",
            "goto": "ask_name"
          },
          {
            "if": "{{has_phone}} == false",
            "goto": "ask_phone"
          },
          {
            "if": "{{has_address}} == false",
            "goto": "ask_address"
          }
        ],
        "else": "order_confirm"
      }
    },

    {
      "id": "ask_name",
      "type": "answer",
      "data": {
        "text": "Anh/chị gửi giúp em tên người nhận ạ 🙏"
      }
    },
    {
      "id": "ask_phone",
      "type": "answer",
      "data": {
        "text": "Anh/chị gửi giúp em SĐT nhận hàng ạ 📞"
      }
    },
    {
      "id": "ask_address",
      "type": "answer",
      "data": {
        "text": "Anh/chị gửi giúp em địa chỉ nhận hàng (quận + tỉnh) ạ 📍"
      }
    },

    {
      "id": "order_confirm",
      "type": "answer",
      "data": {
        "text": "Dạ em xác nhận đơn:\n- Sản phẩm: {{product}}\n- Tên: {{name}}\n- SĐT: {{phone}}\n- Địa chỉ: {{address}}\n\nGiao 2–4 ngày ạ 🚚\nAnh/chị xác nhận giúp em nhé"
      }
    },

    {
      "id": "order_done",
      "type": "answer",
      "data": {
        "text": "Dạ em đã lên đơn thành công 🎉\nĐơn sẽ được giao trong 2–4 ngày ạ 🚚\nCảm ơn anh/chị ❤️"
      }
    },

    // ===== CONSULT =====

    {
      "id": "consult",
      "type": "llm",
      "data": {
        "model": "gpt-4o",
        "prompt": "Tư vấn sản phẩm dựa trên câu hỏi: {{user_query}}"
      }
    },

    // ===== FALLBACK =====

    {
      "id": "fallback",
      "type": "answer",
      "data": {
        "text": "Dạ anh/chị cần em hỗ trợ gì thêm ạ?"
      }
    }
  ]
}