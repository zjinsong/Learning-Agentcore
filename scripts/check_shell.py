"""Parse every Bash tutorial snippet without running any cloud commands."""
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if not shutil.which("bash"):
    print("Bash is unavailable; shell syntax check runs in Linux CI.")
    raise SystemExit(0)
count = 0
for path in ROOT.rglob("*.md"):
    if any(p in {".git", ".local", ".venv"} for p in path.relative_to(ROOT).parts):
        continue
    for index, block in enumerate(re.findall(r"```bash\s*\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S), 1):
        result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(f"{path.relative_to(ROOT)} block {index}: {result.stderr}")
        count += 1
print("Bash snippets parsed:", count)
