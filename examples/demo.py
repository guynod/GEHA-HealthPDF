"""Generate fictional domestic and overseas packets for a quick review."""

import copy
import json
from pathlib import Path
import sys

from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import healthpdf


def run(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    profile = {
        "subscriber": {"name": "Alex Example", "member_id": "DEMO-0000", "plan_name": "EXAMPLE HDHP",
                       "group_number": "DEMO", "address": "123 Example Street, Test City", "email": "alex@example.com", "phone": ""},
        "patients": [{"id": "self", "name": "Alex Example", "dob": "1980-01-02", "relationship": "self"}],
        "insurer": {"name": "GEHA", "claim_email": "GEHA-ClaimSubmission@mygeha.com"},
    }
    receipt = root / "fictional-receipt.pdf"
    pdf = canvas.Canvas(str(receipt))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(36, 740, "FICTIONAL EXAMPLE - DO NOT SUBMIT")
    pdf.setFont("Helvetica", 11)
    for i, line in enumerate(["Patient Alex Example", "Example Clinic, 123 Example Rd", "Date October 1, 2026",
                              "Office visit for neck pain", "Net charge USD 125.00, paid in full"]):
        pdf.drawString(36, 700 - i * 22, line)
    pdf.save()
    domestic = {
        "id": "fictional-domestic", "patient_id": "self", "date_of_service": "2026-10-01",
        "service_country": "United States", "provider": {"name": "Example Clinic", "address": "123 Example Rd, Test City, CA", "tax_id": "123456789"},
        "diagnosis": "Neck pain", "services": ["office_visit"], "amount": {"total": "125.00", "currency": "USD"},
        "evidence": [{"path": str(receipt), "role": "receipt"}],
    }
    first = healthpdf.make_packet(profile, domestic, root / "domestic")
    overseas_receipt = root / "fictional-overseas-receipt.pdf"
    pdf = canvas.Canvas(str(overseas_receipt))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(36, 740, "FICTIONAL EXAMPLE - DO NOT SUBMIT")
    pdf.setFont("Helvetica", 11)
    for i, line in enumerate(["Patient Alex Example", "Example Clinic, 123 Example Rd, Bangkok, Thailand", "Date October 1, 2026",
                              "Physical therapy for neck pain", "Net charge THB 4,300.00, paid in full"]):
        pdf.drawString(36, 700 - i * 22, line)
    pdf.save()
    overseas = copy.deepcopy(domestic)
    overseas.update(id="fictional-overseas", service_country="Thailand", services=["other"], description="Physical therapy for neck pain")
    overseas["provider"]["address"] = "123 Example Rd, Bangkok, Thailand"
    overseas["amount"] = {"total": "4300.00", "currency": "THB"}
    overseas["fx"] = {"usd_per_unit": "0.03", "date": "2026-10-01", "source": "Fictional rate for example only"}
    overseas["evidence"] = [{"path": str(overseas_receipt), "role": "receipt"}]
    saved = json.loads((root / "domestic/progress.json").read_text())
    second = healthpdf.make_packet(profile, overseas, root / "overseas", saved)
    healthpdf.write_json(root / "profile-fictional.json", profile)
    healthpdf.write_json(root / "claim-domestic.json", domestic)
    healthpdf.write_json(root / "claim-overseas.json", overseas)
    return first, second


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "output/demo"
    for packet in run(target):
        print(packet["packet"])
