"""Package the small, provider-neutral upload kit."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = [
    "START-HERE.md", "ASSISTANT-GUIDE.md", "healthpdf.py", "requirements.txt",
    "templates/GEHA-Member-Claim-Submission.pdf", "templates/geha.json",
    "templates/profile-blank.json", "docs/assistant-setup.md",
]


def build():
    target = ROOT / "healthpdf-starter.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            content = (ROOT / name).read_bytes()
            item = zipfile.ZipInfo(name, date_time=(2026, 11, 20, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, content)
    return target


if __name__ == "__main__":
    print(build())
