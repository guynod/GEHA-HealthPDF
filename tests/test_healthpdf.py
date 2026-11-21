"""Synthetic tests of the public entry points and the bundled GEHA form."""

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader
from reportlab.pdfgen import canvas

import healthpdf


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.receipt = self.root / "receipt.pdf"
        self.eob = self.root / "prior-eob.pdf"
        for path, text in [(self.receipt, "FICTIONAL RECEIPT - original evidence"),
                           (self.eob, "FICTIONAL PRIOR EOB - reference only")]:
            pdf = canvas.Canvas(str(path))
            pdf.drawString(36, 700, text)
            pdf.drawString(36, 4, "Bottom-of-page evidence must remain visible")
            pdf.save()
        self.profile = {
            "subscriber": {"name": "Alex Example", "member_id": "DEMO-0000", "plan_name": "EXAMPLE HDHP",
                           "group_number": "DEMO", "address": "123 Example Street, Test City", "email": "alex@example.com", "phone": ""},
            "patients": [{"id": "self", "name": "Alex Example", "dob": "1980-01-02", "relationship": "self"}],
            "insurer": {"name": "GEHA", "claim_email": "GEHA-ClaimSubmission@mygeha.com"},
        }
        self.claim = {
            "id": "demo-expense-1", "patient_id": "self", "date_of_service": "2026-10-01",
            "service_country": "United States", "provider": {"name": "Example Clinic", "address": "123 Example Rd, Test City, CA", "tax_id": "123456789"},
            "diagnosis": "Neck pain", "services": ["office_visit"], "amount": {"total": "125.00", "currency": "USD"},
            "evidence": [{"path": str(self.receipt), "role": "receipt"}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, claim=None, name="packet", progress=None):
        return healthpdf.make_packet(self.profile, claim or self.claim, self.root / name, progress)

    def test_domestic_form_and_source_preservation(self):
        sha = healthpdf.digest(self.receipt)
        result = self.prepare()
        reader = PdfReader(result["packet"])
        self.assertEqual(len(reader.pages), 3)
        form_text = reader.pages[0].extract_text()
        self.assertIn("Alex Example", form_text)
        self.assertIn("EXAMPLE HDHP", form_text)
        self.assertNotIn("United States", form_text)
        self.assertFalse(reader.pages[0].get("/Annots"))
        self.assertIn("Bottom-of-page evidence", reader.pages[-1].extract_text())
        self.assertGreater(reader.pages[-1].mediabox.height, PdfReader(self.receipt).pages[0].mediabox.height)
        self.assertEqual(healthpdf.digest(self.receipt), sha)
        self.assertTrue((self.root / "packet/profile.json").exists())

    def test_overseas_and_documented_usd(self):
        claim = copy.deepcopy(self.claim)
        claim.update(service_country="Thailand", services=["other"], description="Physical therapy for neck pain")
        claim["provider"]["address"] = "123 Example Rd, Bangkok, Thailand"
        claim["amount"] = {"total": "4300.00", "currency": "THB"}
        claim["fx"] = {"actual_usd": "127.41", "date": "2026-10-03", "source": "Fictional card statement, exact matched expense"}
        result = self.prepare(claim)
        text = PdfReader(result["packet"]).pages[0].extract_text()
        self.assertIn("Thailand", text)
        self.assertIn("127.41", text)
        self.assertEqual(result["fx"]["method"], "documented USD payment")

    def test_corrected_packet_order_and_continuity(self):
        first = self.prepare()
        saved = json.loads((self.root / "packet/progress.json").read_text())
        saved["claims"].append({**saved["claims"][0], "claim_id": "another-expense"})
        claim = copy.deepcopy(self.claim)
        claim.update(kind="correction", prior_claim_number="DEMO-PRIOR")
        claim["evidence"] += [{"path": str(self.eob), "role": "prior_eob"}]
        result = self.prepare(claim, "corrected", saved)
        reader = PdfReader(result["packet"])
        self.assertIn("UPDATED/CORRECTED from earlier submission", reader.pages[0].extract_text())
        self.assertIn("FICTIONAL RECEIPT", reader.pages[2].extract_text())
        self.assertIn("FICTIONAL PRIOR EOB", reader.pages[-1].extract_text())
        new = json.loads((self.root / "corrected/progress.json").read_text())
        self.assertEqual(len(new["claims"]), 2)
        self.assertEqual(len(new["history"]), 1)
        self.assertEqual(len(new["packets"]), 2)

    def test_identical_evidence_is_appended_once(self):
        claim = copy.deepcopy(self.claim)
        claim["evidence"] *= 2
        self.assertEqual(len(PdfReader(self.prepare(claim)["packet"]).pages), 3)

    def test_missing_birth_date_produces_no_packet(self):
        self.profile["patients"][0]["dob"] = ""
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / "packet").exists())

    def test_domestic_provider_id_required(self):
        del self.claim["provider"]["tax_id"]
        with self.assertRaisesRegex(ValueError, "tax ID"):
            self.prepare()

    def test_corrected_claim_needs_earlier_eob(self):
        self.claim.update(kind="correction", prior_claim_number="DEMO-PRIOR")
        with self.assertRaisesRegex(ValueError, "prior EOB"):
            self.prepare()

    def test_overflow_rejected(self):
        self.profile["subscriber"]["name"] = "Overlong" * 300
        with self.assertRaisesRegex(ValueError, "fit legibly"):
            self.prepare()
        self.assertFalse((self.root / "packet").exists())

    def test_fx_rounding_and_prior_business_day(self):
        rate = {"usd_per_unit": "0.03005", "date": "2026-09-25", "source": "Fictional historical rate"}
        result = healthpdf.convert("1000.00", "THB", "2026-09-27", rate)
        self.assertEqual(result["usd"], "30.05")
        self.assertEqual(result["date"], "2026-09-25")
        with self.assertRaises(ValueError):
            healthpdf.convert("1000", "THB", "2026-09-24", rate)

    def test_eob_reconciliation_preserves_independent_evidence(self):
        self.prepare()
        eob = {"claim_id": "demo-expense-1", "patient": "Alex Example", "service_date": "2026-10-01",
               "insurer_claim_number": "DEMO-EOB-1", "notice_date": "2026-10-05", "status": "paid", "billed_usd": "125.00",
               "paid_usd": "118.75", "member_share_usd": "6.25", "path": str(self.eob)}
        rows = healthpdf.reconcile(self.root / "packet/tracker.csv", eob)
        self.assertEqual(rows[0]["payment_proof"], "unknown")
        self.assertEqual(rows[0]["hsa_reimbursed"], "no")
        self.assertEqual(rows[0]["insurer_deposit_verified"], "")
        self.assertEqual(rows[0]["member_share_usd"], "6.25")
        eob["patient"] = "Different Patient"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            healthpdf.reconcile(self.root / "packet/tracker.csv", eob)

    def test_output_revision_preserves_previous(self):
        result = self.prepare()
        sha = healthpdf.digest(result["packet"])
        with self.assertRaisesRegex(ValueError, "new output folder"):
            self.prepare()
        self.assertEqual(healthpdf.digest(result["packet"]), sha)

    def test_correction_retains_reimbursement_and_insurance_facts(self):
        self.prepare()
        saved = json.loads((self.root / "packet/progress.json").read_text())
        facts = {"hsa_reimbursed": "yes", "insurer_deposit_verified": "yes", "eob_saved": "yes",
                 "submitted_date": "2026-10-02", "insurer_claim_number": "DEMO-PRIOR", "insurer_paid_usd": "100.00"}
        saved["claims"][0].update(facts)
        claim = copy.deepcopy(self.claim)
        claim.update(kind="correction", prior_claim_number="DEMO-PRIOR")
        claim["evidence"].append({"path": str(self.eob), "role": "prior_eob"})
        self.prepare(claim, "corrected", saved)
        current = json.loads((self.root / "corrected/progress.json").read_text())["claims"][0]
        self.assertEqual({key: current[key] for key in facts}, facts)
        self.assertEqual(current["submission_status"], "correction_prepared")

    def test_actual_usd_email_uses_documented_payment(self):
        claim = copy.deepcopy(self.claim)
        claim["service_country"] = "Thailand"
        claim["amount"] = {"total": "4300.00", "currency": "THB"}
        claim["fx"] = {"actual_usd": "127.41", "date": "2026-10-03", "source": "Exact fictional card payment"}
        self.prepare(claim)
        body = (self.root / "packet/email-draft.txt").read_text()
        self.assertIn("documented USD payment is $127.41", body)
        self.assertNotIn("date-of-care conversion", body)

    def test_updated_eob_progress_survives_next_claim(self):
        self.prepare()
        saved = json.loads((self.root / "packet/progress.json").read_text())
        eob = {"claim_id": "demo-expense-1", "patient": "Alex Example", "service_date": "2026-10-01",
               "insurer_claim_number": "DEMO-EOB-1", "notice_date": "2026-10-05", "status": "paid", "billed_usd": "125.00",
               "paid_usd": "118.75", "member_share_usd": "6.25", "path": str(self.eob)}
        rows = healthpdf.reconcile(self.root / "packet/tracker.csv", eob)
        healthpdf.save_reconciled_progress(self.root / "updated-progress.json", rows, eob, saved)
        updated = json.loads((self.root / "updated-progress.json").read_text())
        claim = copy.deepcopy(self.claim)
        claim["id"] = "next-expense"
        self.prepare(claim, "next", updated)
        final = json.loads((self.root / "next/progress.json").read_text())
        old = next(row for row in final["claims"] if row["claim_id"] == "demo-expense-1")
        self.assertEqual(old["insurer_paid_usd"], "118.75")
        self.assertEqual(len(final["eobs"]), 1)

    def test_generic_mapping_can_omit_optional_plan_fields(self):
        spec = json.loads((healthpdf.ROOT / "templates/geha.json").read_text())
        spec["template"] = str(healthpdf.ROOT / "templates/GEHA-Member-Claim-Submission.pdf")
        spec["required_subscriber"] = ["name", "member_id"]
        mapping = self.root / "custom.json"
        mapping.write_text(json.dumps(spec))
        self.claim["template_spec"] = str(mapping)
        del self.profile["subscriber"]["plan_name"]
        del self.profile["subscriber"]["group_number"]
        self.assertTrue(Path(self.prepare()["packet"]).is_file())


if __name__ == "__main__":
    unittest.main()
