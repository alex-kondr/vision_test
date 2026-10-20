import sys
sys.stdout.reconfigure(encoding='utf-8')

content = open('app.py', 'r', encoding='utf-8').read()
lines = content.split('\n')

# Замінюємо рядки 509-518 (0-indexed: 508-517)
# Рядок 510 (0-idx 509): '            if action.template_b64 and getattr...' — погано
# Рядки 511-518 (0-idx 510-517): з подвійним відступом

new_block = [
    '                if action.template_b64 and getattr(action, "use_vision", True):',
    '                    bank = getattr(action, "template_bank", [])',
    '                    bank_count = len(bank) if bank else 1',
    '                    vision_badge = f"\U0001f916\U0001f3af {action.template_width}x{action.template_height} [x{bank_count}]"',
    '                elif action.template_b64:',
    '                    vision_badge = "\u0412\u0438\u043c\u043a\u043d\u0435\u043d\u043e"',
    '                else:',
    '                    vision_badge = "\u0422\u0456\u043b\u044c\u043a\u0438 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u0438"',
    '                tag = "click"',
]

# Замінюємо рядки 509..518 (0-indexed)
lines[509:519] = new_block

content = '\n'.join(lines)
open('app.py', 'w', encoding='utf-8').write(content)
print("Fixed! Lines 510-519 replaced.")
