#!/usr/bin/env python3
"""Patch Dify_cskh_dsl.yml to add human handoff tags."""

import re
import shutil
from pathlib import Path

FILE = Path('/Users/phamthidung/Documents/weup-cskh/Dify_cskh_dsl.yml')

# Backup
shutil.copy(FILE, FILE.with_suffix('.yml.bak'))
print(f"Backup: {FILE.with_suffix('.yml.bak')}")

with open(FILE, 'r', encoding='utf-8') as f:
    content = f.read()

errors = []

def replace_once(content, old, new, label):
    count = content.count(old)
    if count == 0:
        errors.append(f"NOT FOUND: {label}")
        return content
    if count > 1:
        errors.append(f"AMBIGUOUS ({count} matches): {label}")
        return content
    print(f"OK: {label}")
    return content.replace(old, new, 1)

# ============================================================
# CHANGE 1: confirm_llm — thêm OUTPUT FORMAT vào cuối prompt
# Anchor: đoạn text cuối của confirm_llm rồi tới node attributes
# ============================================================
content = replace_once(
    content,
    '                - Luôn xưng **"em"**, gọi khách là **"anh/chị"**\n'
    '                - Trả lời đúng ngôn ngữ khách đang dùng\n'
    '          selected: false\n'
    '          title: "LLM X\\xE1c nh\\u1EADn \\u0111\\u01A1n"',
    '                - Luôn xưng **"em"**, gọi khách là **"anh/chị"**\n'
    '                - Trả lời đúng ngôn ngữ khách đang dùng\n'
    '\n'
    '                ## OUTPUT FORMAT\n'
    '                Chỉ trả về JSON thuần, không giải thích:\n'
    '                {\n'
    '                  "confirmed": true,\n'
    '                  "text": "nội dung trả lời cho khách"\n'
    '                }\n'
    '                confirmed = true: khi đã đủ 4 thông tin và đã xác nhận đơn thành công.\n'
    '                confirmed = false: khi còn thiếu thông tin hoặc đang hỏi thêm.\n'
    '          selected: false\n'
    '          title: "LLM X\\xE1c nh\\u1EADn \\u0111\\u01A1n"',
    'CHANGE 1: confirm_llm OUTPUT FORMAT'
)

# ============================================================
# CHANGE 2: confirm_output_guard — rewrite code để parse JSON + append tag
# Anchor: value_selector [confirm_llm, text] — unique
# ============================================================
old_confirm_guard_code = '''\
          code: |
            import re

            def main(arg1: str) -> dict:
                cleaned = arg1
                cleaned = re.sub(r'\\[[A-Z]+\\.[A-Z0-9]+\\]', '', cleaned)
                cleaned = re.sub(r'\\bDA\\d+\\b', '', cleaned)
                cleaned = re.sub(r'D\\u1ef1 \\xe1n:\\s*\\S+', '', cleaned)
                cleaned = re.sub(r'Th\\u1ecb tr\\u01b0\\u1eddng:\\s*[^\\n|]+', '', cleaned)
                cleaned = re.sub(r'Lo\\u1ea1i:\\s*[^\\n|]+', '', cleaned)
                cleaned = re.sub(r'  +', ' ', cleaned).strip()
                if not cleaned:
                    cleaned = arg1
                return {"output": cleaned}
          code_language: python3
          desc: "L\\u1ecdc m\\xe3 DA tr\\u01b0\\u1edbc khi tr\\u1ea3 v\\u1ec1 kh\\xe1ch"
          outputs:
            output: {children: null, type: string}
          selected: false
          title: "Output Guard (X\\xe1c nh\\u1eadn \\u0111\\u01a1n)"
          type: code
          variables:
          - value_selector: [confirm_llm, text]
            value_type: string
            variable: arg1'''

# Try to find the confirm_output_guard by its unique variable selector
old_confirm_guard = '          - value_selector: [confirm_llm, text]\n            value_type: string\n            variable: arg1\n        height: 54\n        id: confirm_output_guard'

new_confirm_guard_code = (
    '          code: |\n'
    '            import re\n'
    '            import json\n'
    '\n'
    '            def main(arg1: str) -> dict:\n'
    '                try:\n'
    '                    cleaned = arg1.replace("\\xa0", " ").strip()\n'
    '                    if "```" in cleaned:\n'
    '                        lines = cleaned.split("\\n")\n'
    '                        lines = [l for l in lines if not l.strip().startswith("```")]\n'
    '                        cleaned = "\\n".join(lines)\n'
    '                    data = json.loads(cleaned)\n'
    '                    confirmed = bool(data.get("confirmed", False))\n'
    '                    text = str(data.get("text", arg1))\n'
    '                except Exception:\n'
    '                    confirmed = False\n'
    '                    text = arg1\n'
    '                text = re.sub(r\'\\\\[[A-Z]+\\\\.[A-Z0-9]+\\\\]\', \'\', text)\n'
    '                text = re.sub(r\'\\\\bDA\\\\d+\\\\b\', \'\', text)\n'
    '                text = re.sub(r\'  +\', \' \', text).strip()\n'
    '                if not text:\n'
    '                    text = arg1\n'
    '                if confirmed:\n'
    '                    text = text + "\\n[[HANDOFF:ORDER:hard]]"\n'
    '                return {"output": text}\n'
)

# Find the confirm_output_guard code block by locating the unique variable selector
idx = content.find('          - value_selector: [confirm_llm, text]\n            value_type: string\n            variable: arg1\n        height: 54\n        id: confirm_output_guard')
if idx == -1:
    errors.append('NOT FOUND: confirm_output_guard anchor')
else:
    # Find start of code block — go backward to find '          code: |'
    code_start = content.rfind('\n          code: |', 0, idx)
    if code_start == -1:
        errors.append('NOT FOUND: confirm_output_guard code start')
    else:
        old_block = content[code_start+1:idx]
        new_block = new_confirm_guard_code
        content = content[:code_start+1] + new_block + content[idx:]
        print('OK: CHANGE 2: confirm_output_guard code')

# ============================================================
# CHANGE 3: complaint_llm — thêm OUTPUT FORMAT vào cuối prompt
# Anchor: đoạn cuối prompt complaint_llm — "KHÔNG cam kết kết quả..."
# ============================================================
content = replace_once(
    content,
    '                - **KHÔNG** cam kết kết quả cụ thể khi chưa kiểm tra\n'
    '                - Luôn xưng **"em"**, gọi khách là **"anh/chị"**\n'
    '                - Trả lời đúng ngôn ngữ khách đang dùng\n'
    '          selected: false\n'
    '          title: "LLM Khi\\u1EBFu n\\u1EA1i"',
    '                - **KHÔNG** cam kết kết quả cụ thể khi chưa kiểm tra\n'
    '                - Luôn xưng **"em"**, gọi khách là **"anh/chị"**\n'
    '                - Trả lời đúng ngôn ngữ khách đang dùng\n'
    '\n'
    '                ## OUTPUT FORMAT\n'
    '                Chỉ trả về JSON thuần, không giải thích:\n'
    '                {\n'
    '                  "need_handoff": true,\n'
    '                  "text": "nội dung trả lời cho khách"\n'
    '                }\n'
    '                need_handoff = true: TRACKING, HỦY/THAY ĐỔI, KHIẾU NẠI.\n'
    '                need_handoff = false: chỉ hỏi thời gian giao chung.\n'
    '          selected: false\n'
    '          title: "LLM Khi\\u1EBFu n\\u1EA1i"',
    'CHANGE 3: complaint_llm OUTPUT FORMAT'
)

# ============================================================
# CHANGE 4: complaint_answer — reference complaint_code.output
# ============================================================
content = replace_once(
    content,
    "          answer: '{{#complaint_llm.text#}}'",
    "          answer: '{{#complaint_code.output#}}'",
    'CHANGE 4: complaint_answer reference'
)

# ============================================================
# CHANGE 5: fallback answer — reference fallback_code.output
# ============================================================
content = replace_once(
    content,
    "          answer: '{{#fallback_llm.text#}}'",
    "          answer: '{{#fallback_code.output#}}'",
    'CHANGE 5: fallback answer reference'
)

# ============================================================
# CHANGE 6: offtopic_answer — reference offtopic_code.output
# ============================================================
content = replace_once(
    content,
    "          answer: '{{#offtopic_llm.text#}}'",
    "          answer: '{{#offtopic_code.output#}}'",
    'CHANGE 6: offtopic_answer reference'
)

# ============================================================
# CHANGE 7: blocked_answer — reference blocked_code.output
# ============================================================
content = replace_once(
    content,
    '          answer: "D\\u1EA1, em kh\\xF4ng th\\u1EC3 x\\u1EED l\\xFD y\\xEAu c\\u1EA7u n\\xE0y \\u1EA1. Anh/ch\\u1ECB c\\u1EA7n t\\u01B0 v\\u1EA5n s\\xE1ch ho\\u1EB7c \\u0111\\u1EB7t h\\xE0ng, em lu\\xF4n s\\u1EB5n s\\xE0ng gi\\xFAp \\u1EA1 \\U0001F64F"',
    "          answer: '{{#blocked_code.output#}}'",
    'CHANGE 7: blocked_answer reference'
)

# ============================================================
# CHANGE 8: Remove old edges, add new edges
# ============================================================

# Remove e-complaint-ans
content = replace_once(
    content,
    '      # Complaint LLM → Answer\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: answer}\n'
    '        id: e-complaint-ans\n'
    '        selected: false\n'
    '        source: complaint_llm\n'
    '        sourceHandle: source\n'
    '        target: complaint_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    '      # Complaint LLM → Code → Answer\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: code}\n'
    '        id: e-complaint-code\n'
    '        selected: false\n'
    '        source: complaint_llm\n'
    '        sourceHandle: source\n'
    '        target: complaint_code\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n'
    '\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: code, targetType: answer}\n'
    '        id: e-complaint-code-ans\n'
    '        selected: false\n'
    '        source: complaint_code\n'
    '        sourceHandle: source\n'
    '        target: complaint_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    'CHANGE 8a: complaint edges'
)

# Remove e-fallback-ans
content = replace_once(
    content,
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: answer}\n'
    '        id: e-fallback-ans\n'
    '        selected: false\n'
    '        source: fallback_llm\n'
    '        sourceHandle: source\n'
    '        target: fallback\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: code}\n'
    '        id: e-fallback-code\n'
    '        selected: false\n'
    '        source: fallback_llm\n'
    '        sourceHandle: source\n'
    '        target: fallback_code\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n'
    '\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: code, targetType: answer}\n'
    '        id: e-fallback-code-ans\n'
    '        selected: false\n'
    '        source: fallback_code\n'
    '        sourceHandle: source\n'
    '        target: fallback\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    'CHANGE 8b: fallback edges'
)

# Remove e-offtopic-ans
content = replace_once(
    content,
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: answer}\n'
    '        id: e-offtopic-ans\n'
    '        selected: false\n'
    '        source: offtopic_llm\n'
    '        sourceHandle: source\n'
    '        target: offtopic_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    '      - data: {isInIteration: false, isInLoop: false, sourceType: llm, targetType: code}\n'
    '        id: e-offtopic-code\n'
    '        selected: false\n'
    '        source: offtopic_llm\n'
    '        sourceHandle: source\n'
    '        target: offtopic_code\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n'
    '\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: code, targetType: answer}\n'
    '        id: e-offtopic-code-ans\n'
    '        selected: false\n'
    '        source: offtopic_code\n'
    '        sourceHandle: source\n'
    '        target: offtopic_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    'CHANGE 8c: offtopic edges'
)

# Remove e-safety-blocked, add blocked_code edges
content = replace_once(
    content,
    '      # Safety Router → Blocked\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: if-else, targetType: answer}\n'
    '        id: e-safety-blocked\n'
    '        selected: false\n'
    '        source: safety_router\n'
    '        sourceHandle: case_blocked\n'
    '        target: blocked_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    '      # Safety Router → Blocked Code → Blocked Answer\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: if-else, targetType: code}\n'
    '        id: e-safety-blocked-code\n'
    '        selected: false\n'
    '        source: safety_router\n'
    '        sourceHandle: case_blocked\n'
    '        target: blocked_code\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n'
    '\n'
    '      - data: {isInIteration: false, isInLoop: false, sourceType: code, targetType: answer}\n'
    '        id: e-blocked-code-ans\n'
    '        selected: false\n'
    '        source: blocked_code\n'
    '        sourceHandle: source\n'
    '        target: blocked_answer\n'
    '        targetHandle: target\n'
    '        type: custom\n'
    '        zIndex: 0\n',
    'CHANGE 8d: blocked edges'
)

# ============================================================
# CHANGE 9: Add new nodes before viewport section
# ============================================================
new_nodes = '''
      # ===== COMPLAINT CODE (parse JSON + handoff tag) =====
      - data:
          code: |
            import json

            def main(arg1: str) -> dict:
                try:
                    cleaned = arg1.replace("\\xa0", " ").strip()
                    if "```" in cleaned:
                        lines = cleaned.split("\\n")
                        lines = [l for l in lines if not l.strip().startswith("```")]
                        cleaned = "\\n".join(lines)
                    data = json.loads(cleaned)
                    need_handoff = bool(data.get("need_handoff", False))
                    text = str(data.get("text", arg1))
                except Exception:
                    need_handoff = False
                    text = arg1
                if need_handoff:
                    text = text + "\\n[[HANDOFF:COMPLAINT:hard]]"
                return {"output": text}
          code_language: python3
          desc: "Parse JSON + handoff tag khi khiếu nại"
          outputs:
            output: {children: null, type: string}
          selected: false
          title: "Handoff Complaint"
          type: code
          variables:
          - value_selector: [complaint_llm, text]
            value_type: string
            variable: arg1
        height: 54
        id: complaint_code
        position: {x: 1430, y: 720}
        positionAbsolute: {x: 1430, y: 720}
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244

      # ===== FALLBACK CODE (handoff tag) =====
      - data:
          code: |
            def main(arg1: str) -> dict:
                return {"output": arg1 + "\\n[[HANDOFF:FALLBACK:soft]]"}
          code_language: python3
          desc: "Gắn soft handoff tag cho fallback"
          outputs:
            output: {children: null, type: string}
          selected: false
          title: "Handoff Fallback"
          type: code
          variables:
          - value_selector: [fallback_llm, text]
            value_type: string
            variable: arg1
        height: 54
        id: fallback_code
        position: {x: 1430, y: 940}
        positionAbsolute: {x: 1430, y: 940}
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244

      # ===== OFFTOPIC CODE (handoff tag) =====
      - data:
          code: |
            def main(arg1: str) -> dict:
                return {"output": arg1 + "\\n[[HANDOFF:OFFTOPIC:soft]]"}
          code_language: python3
          desc: "Gắn soft handoff tag cho off-topic"
          outputs:
            output: {children: null, type: string}
          selected: false
          title: "Handoff Off-topic"
          type: code
          variables:
          - value_selector: [offtopic_llm, text]
            value_type: string
            variable: arg1
        height: 54
        id: offtopic_code
        position: {x: 1430, y: 960}
        positionAbsolute: {x: 1430, y: 960}
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244

      # ===== BLOCKED CODE (static text + handoff tag) =====
      - data:
          code: |
            def main() -> dict:
                text = "Dạ, em không thể xử lý yêu cầu này ạ. Anh/chị cần tư vấn sách hoặc đặt hàng, em luôn sẵn sàng giúp ạ 🙏"
                return {"output": text + "\\n[[HANDOFF:BLOCKED:soft]]"}
          code_language: python3
          desc: "Blocked response + soft handoff tag"
          outputs:
            output: {children: null, type: string}
          selected: false
          title: "Blocked + Handoff"
          type: code
          variables: []
        height: 54
        id: blocked_code
        position: {x: 930, y: 160}
        positionAbsolute: {x: 930, y: 160}
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244

'''

content = replace_once(
    content,
    '    viewport:\n',
    new_nodes + '    viewport:\n',
    'CHANGE 9: Add new nodes'
)

# ============================================================
# Write output
# ============================================================
if errors:
    print('\n❌ ERRORS:')
    for e in errors:
        print(f'  - {e}')
    print('\nFile NOT written due to errors.')
else:
    with open(FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    print('\n✅ All changes applied successfully.')
