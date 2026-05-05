import sys

try:
    compile(open("backend/breakout.py").read(), "backend/breakout.py", "exec")
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)
