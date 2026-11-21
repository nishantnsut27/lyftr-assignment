import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(rb"gsk_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(rb"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    candidates = (
        subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    findings: list[str] = []
    for filename in dict.fromkeys(name for name in candidates if name):
        path = root / filename
        if not path.is_file():
            continue
        if path.name == ".env" or (
            path.name.startswith(".env.") and not path.name.endswith(".example")
        ):
            findings.append(f"{filename}: private environment file must not be tracked")
            continue
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            findings.append(f"{filename}: credential pattern found")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(
        f"PASS credential pattern scan: {len(set(candidates) - {''})} non-ignored repository files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
