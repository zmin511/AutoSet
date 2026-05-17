import sys

from docx import Document


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) != 2:
        print("Usage: dump_docx.py <path.docx>")
        return 2
    path = sys.argv[1]
    doc = Document(path)
    lines = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            lines.append(t)
    print(f"lines={len(lines)}")
    for t in lines:
        print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
