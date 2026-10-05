"""Check public source syntax, local links, configurations and obvious secrets."""
import ast
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".git", ".local", ".secrets", ".venv", "__pycache__"}


def main():
    failures = []
    counts = {"python": 0, "links": 0, "configurations": 0, "files": 0}
    patterns = {
        "AWS access key": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "private key": r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
        "account number": r"(?<![\d.])\d{12}(?![\d.])",
        "external IPv4": r"\b(?!(?:127\.0\.0\.1|0\.0\.0\.0)\b)(?:\d{1,3}\.){3}\d{1,3}\b",
        "user path": r"[Cc]:[\\/](?:Users|kiro)[\\/]",
    }
    for path in ROOT.rglob("*"):
        if not path.is_file() or EXCLUDE.intersection(path.relative_to(ROOT).parts):
            continue
        content = path.read_text(encoding="utf-8")
        counts["files"] += 1
        if path.suffix == ".py":
            ast.parse(content, filename=str(path))
            counts["python"] += 1
        for label, pattern in patterns.items():
            if re.search(pattern, content):
                failures.append(f"{path.relative_to(ROOT)}: {label}")
        if path.suffix != ".md":
            continue
        for snippet in re.findall(r"```python\s*\n(.*?)\n```", content, re.S):
            ast.parse(snippet, filename=str(path))
        for kind, snippet in re.findall(r"```(json|toml)\s*\n(.*?)\n```", content, re.S):
            (json.loads if kind == "json" else tomllib.loads)(snippet)
            counts["configurations"] += 1
        for target in re.findall(r"\]\(([^\s)]+)\)", content):
            if target.startswith(("https://", "http://", "#", "mailto:")):
                continue
            counts["links"] += 1
            destination = (path.parent / target.split("#")[0]).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                failures.append(f"{path.relative_to(ROOT)}: broken link {target}")
    if failures:
        raise SystemExit("\n".join(failures))
    print("Public source checks passed:", counts)


if __name__ == "__main__":
    main()
