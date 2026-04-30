import sys
sys.path.insert(0, ".")
from app.agent.core import _is_dismissal

cases = [
    ("No, that's all I need", True),
    ("No, that's all", True),
    ("that's all I need", True),
    ("that's fine", True),
    ("Thanks!", True),
    ("I'm good", True),
    ("okay thanks", True),
    ("never mind", True),
    ("got it thanks", True),
    ("No thanks", True),
    ("How do I block my card?", False),
    ("yes please", False),
    ("What is BEFTN?", False),
    ("I need more help", False),
]

ok = True
for msg, expected in cases:
    result = _is_dismissal(msg)
    status = "OK" if result == expected else "FAIL"
    if result != expected:
        ok = False
    print(f"[{status}] {msg!r} -> {result} (expected {expected})")

print()
print("All tests passed!" if ok else "SOME TESTS FAILED")
