"""Synthetic tests of the public entry points and the bundled GEHA form."""

import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject, NumberObject, NameObject, ArrayObject, FloatObject, BooleanObject, TextStringObject, DictionaryObject
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

    def test_three_decimal_invoice_precision_survives_packet_and_tracker(self):
        for currency, country in {"BHD": "Bahrain", "IQD": "Iraq", "JOD": "Jordan", "KWD": "Kuwait",
                                  "LYD": "Libya", "OMR": "Oman", "TND": "Tunisia"}.items():
            with self.subTest(currency=currency):
                claim = copy.deepcopy(self.claim)
                claim["service_country"] = country
                claim["provider"]["address"] = "123 Example Road, " + country
                claim["amount"] = {"total": "10.125", "currency": currency}
                claim["fx"] = {"usd_per_unit": "3.2", "date": "2026-10-01", "source": "Fictional precision test"}
                result = self.prepare(claim, currency)
                with (self.root / currency / "tracker.csv").open() as f:
                    row = next(csv.DictReader(f))
                self.assertEqual(row["original_amount"], "10.125")
                self.assertEqual(row["submitted_usd"], "32.40")
                self.assertIn("10.125 " + currency, (self.root / currency / "email-draft.txt").read_text())
                self.assertIn("32.40", PdfReader(result["packet"]).pages[0].extract_text())
        precise = healthpdf.convert("1.235", "KWD", "2026-10-01",
                                    {"usd_per_unit": "3.2", "date": "2026-10-01", "source": "Fictional rate"})
        self.assertEqual(precise["usd"], "3.95")

    def test_currency_precision_rejects_unsupported_fractions(self):
        for value, currency in [("10.125", "USD"), ("10.125", "THB"), ("10.1234", "KWD"), ("10.1", "JPY")]:
            with self.subTest(value=value, currency=currency), self.assertRaises(ValueError):
                healthpdf.money(value, currency)
        self.assertEqual(str(healthpdf.money("125", "JPY")), "125")
        with self.assertRaises(ValueError):
            healthpdf.convert("1.234", "KWD", "2026-10-01",
                               {"actual_usd": "4.125", "date": "2026-10-01", "source": "Fictional payment"})

    def test_eob_name_presentation_changes_preserve_patient_identity(self):
        self.prepare()
        eob = {"claim_id": "demo-expense-1", "patient": "Alex Example", "service_date": "2026-10-01",
               "insurer_claim_number": "DEMO-EOB", "notice_date": "2026-10-05", "status": "paid",
               "billed_usd": "125.00", "paid_usd": "125.00", "member_share_usd": "0.00", "path": str(self.eob)}
        for patient in ("ALEX EXAMPLE", " EXAMPLE, ALEX ", "Alex   Example", "Ａｌｅｘ Ｅｘａｍｐｌｅ"):
            with self.subTest(patient=patient):
                rows = healthpdf.reconcile(self.root / "packet/tracker.csv", {**eob, "patient": patient})
                self.assertEqual(rows[0]["patient"], "Alex Example")
                self.assertEqual(rows[0]["insurer_paid_usd"], "125.00")
        for change in ({"patient": "Alex J Example"}, {"patient": "A Example"}, {"patient": "Alec Example"},
                       {"service_date": "2026-10-02"}, {"claim_id": "another-claim"}, {"paid_usd": "125.001"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                healthpdf.reconcile(self.root / "packet/tracker.csv", {**eob, **change})
        with (self.root / "packet/tracker.csv").open() as f:
            row = next(csv.DictReader(f))
        healthpdf.save_tracker(self.root / "duplicates.csv", [row, row])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            healthpdf.reconcile(self.root / "duplicates.csv", eob)

    def test_fillable_receipt_is_static_in_the_complete_packet(self):
        form = self.root / "filled-receipt.pdf"
        pdf = canvas.Canvas(str(form), pagesize=(612, 792))
        pdf.drawString(36, 730, "FICTIONAL RECEIPT - DO NOT SUBMIT")
        pdf.acroForm.textfield(name="total", value="THB 4,300.00", x=36, y=630, width=200, height=30, fontSize=14)
        pdf.acroForm.checkbox(name="paid", checked=True, x=36, y=580)
        pdf.save()
        original = PdfReader(form)
        checked = original.pages[0]["/Annots"][1].get_object()
        checked_stream = checked["/AP"]["/N"][checked["/AS"]].get_data()
        before = healthpdf.digest(form)
        claim = copy.deepcopy(self.claim)
        claim.update(service_country="Thailand", amount={"total": "4300.00", "currency": "THB"},
                     fx={"actual_usd": "127.41", "date": "2026-10-01", "source": "Fictional payment"},
                     evidence=[{"path": str(form), "role": "receipt"}])
        result = self.prepare(claim)
        packet = PdfReader(result["packet"])
        self.assertFalse(packet.get_fields())
        self.assertFalse(any(ref.get_object().get("/Subtype") == "/Widget"
                             for page in packet.pages for ref in page.get("/Annots", [])))
        self.assertIn("THB 4,300.00", packet.pages[-1].extract_text())
        appearances = packet.pages[-1]["/Resources"]["/XObject"].values()
        self.assertIn(checked_stream, [ref.get_object().get_data() for ref in appearances])
        self.assertEqual(healthpdf.digest(form), before)

    def test_stale_need_appearances_receipt_is_rejected_before_output(self):
        for indirect_flag in (False, True):
            for cover in (False, True):
                with self.subTest(indirect_flag=indirect_flag, cover=cover):
                    stream = io.BytesIO()
                    pdf = canvas.Canvas(stream, pagesize=(612, 792))
                    pdf.drawString(36, 730, "FICTIONAL STALE-FIELD RECEIPT")
                    pdf.acroForm.textfield(name="total", value="THB 4,300.00", x=36, y=630, width=200, height=30, fontSize=14)
                    pdf.save()
                    stream.seek(0)
                    writer = PdfWriter(clone_from=PdfReader(stream))
                    widget = writer.pages[0]["/Annots"][0].get_object()
                    widget[NameObject("/V")] = TextStringObject("THB 9,999.00")
                    self.assertIn(b"4,300.00", widget["/AP"]["/N"].get_data())
                    flag = BooleanObject(True)
                    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = writer._add_object(flag) if indirect_flag else flag
                    if cover:
                        writer.insert_blank_page(width=612, height=792, index=0)
                    path = self.root / f"stale-{indirect_flag}-{cover}.pdf"
                    with path.open("wb") as out:
                        writer.write(out)
                    before = healthpdf.digest(path)
                    claim = copy.deepcopy(self.claim)
                    claim["evidence"] = [{"path": str(path), "role": "receipt"}]
                    folder = f"refused-{indirect_flag}-{cover}"
                    with self.assertRaisesRegex(ValueError, "render a copy to a static PDF"):
                        self.prepare(claim, folder)
                    self.assertFalse((self.root / folder).exists())
                    self.assertEqual(healthpdf.digest(path), before)

    def test_false_need_appearances_and_fieldless_pdf_remain_accepted(self):
        for widgets, need_appearances in ((True, False), (False, True)):
            with self.subTest(widgets=widgets, need_appearances=need_appearances):
                stream = io.BytesIO()
                pdf = canvas.Canvas(stream, pagesize=(612, 792))
                pdf.drawString(36, 730, "FICTIONAL RECEIPT")
                if widgets:
                    pdf.acroForm.textfield(name="total", value="THB 4,300.00", x=36, y=630, width=200, height=30)
                pdf.save()
                stream.seek(0)
                writer = PdfWriter(clone_from=PdfReader(stream))
                if "/AcroForm" not in writer._root_object:
                    writer._root_object[NameObject("/AcroForm")] = DictionaryObject()
                writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(need_appearances)
                path = self.root / f"accepted-{widgets}.pdf"
                with path.open("wb") as out:
                    writer.write(out)
                reader = healthpdf.source_pdf(path)
                output = healthpdf.annotate_member(reader.pages[0], "DEMO-0000")
                self.assertIn("FICTIONAL RECEIPT", output.extract_text())
                if widgets:
                    self.assertIn("THB 4,300.00", output.extract_text())


class EvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def page(self):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(200, 300))
        pdf.drawString(20, 25, "VISIBLE BOTTOM")
        pdf.save()
        stream.seek(0)
        return PdfWriter().add_page(PdfReader(stream).pages[0])

    def form_page(self):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(240, 340))
        pdf.drawString(25, 300, "FICTIONAL FILLABLE RECEIPT")
        pdf.acroForm.textfield(name="total", value="THB 4,300.00", x=40, y=200, width=140, height=24, fontSize=12)
        pdf.acroForm.checkbox(name="paid", checked=True, x=40, y=160)
        pdf.save()
        stream.seek(0)
        return PdfWriter().add_page(PdfReader(stream).pages[0])

    def assert_footer(self, page):
        positions = []
        def visit(text, cm, tm, font, size):
            if "Member ID DEMO-0000" in text:
                positions.append(Transformation(cm).apply_on((tm[4], tm[5])))
        page.extract_text(visitor_text=visit)
        self.assertEqual(page.rotation, 0)
        self.assertEqual(list(page.cropbox), list(page.mediabox))
        self.assertEqual(tuple(page.mediabox.lower_left), (0, 0))
        self.assertEqual(len(positions), 1)
        self.assertAlmostEqual(positions[0][0], 12)
        self.assertAlmostEqual(positions[0][1], 3)

    def test_phone_photo_is_letter_sized_oriented_and_original_unchanged(self):
        path = self.root / "phone-12mp.jpg"
        photo = Image.new("RGB", (4032, 3024), "white")
        ImageDraw.Draw(photo).text((30, 30), "FICTIONAL PHOTO RECEIPT", fill="black", font_size=72)
        exif = photo.getexif()
        exif[274] = 6
        photo.save(path, exif=exif)
        before = healthpdf.digest(path)
        source = healthpdf.source_pdf(path).pages[0]
        image = list(source.images)[0].image
        self.assertEqual(image.size, (1800, 2400))
        output = healthpdf.annotate_member(source, "DEMO-0000")
        self.assertEqual((float(output.mediabox.width), float(output.mediabox.height)), (612, 792))
        self.assert_footer(output)
        self.assertEqual(healthpdf.digest(path), before)

    def test_heic_and_heif_decode_with_actionable_missing_dependency(self):
        from pillow_heif import register_heif_opener
        register_heif_opener()
        for suffix in (".heic", ".heif"):
            path = self.root / ("phone" + suffix)
            Image.new("RGB", (160, 96), "white").save(path, format="HEIF")
            before = healthpdf.digest(path)
            page = healthpdf.annotate_member(healthpdf.source_pdf(path).pages[0], "DEMO-0000")
            self.assertEqual(len(list(page.images)), 1)
            self.assertEqual((float(page.mediabox.width), float(page.mediabox.height)), (612, 792))
            self.assertEqual(healthpdf.digest(path), before)
        with mock.patch.dict("sys.modules", {"pillow_heif": None}):
            with self.assertRaisesRegex(ValueError, "convert a copy to JPEG"):
                healthpdf.source_pdf(path)

    def test_rotated_and_offset_pages_have_upright_visible_footers(self):
        for rotation in (0, 90, 180, 270):
            for offset in ((0, 0), (100, 200), (-60, -80)):
                with self.subTest(rotation=rotation, offset=offset):
                    page = self.page()
                    x, y = offset
                    page.add_transformation(Transformation().translate(tx=x, ty=y))
                    page.mediabox = RectangleObject((x, y, x + 200, y + 300))
                    page.cropbox = page.mediabox
                    page.rotate(rotation)
                    output = healthpdf.annotate_member(page, "DEMO-0000")
                    width, height = (300, 200) if rotation in (90, 270) else (200, 300)
                    self.assertAlmostEqual(float(output.mediabox.width), width)
                    self.assertAlmostEqual(float(output.mediabox.height), height + 14)
                    self.assert_footer(output)
                    self.assertIn("VISIBLE BOTTOM", output.extract_text())

    def test_crop_and_user_units_keep_the_displayed_page_bounds(self):
        for rotation in (0, 90, 180, 270):
            page = self.page()
            page.cropbox = RectangleObject((20, 40, 180, 260))
            page[NameObject("/UserUnit")] = NumberObject(2)
            page.rotate(rotation)
            output = healthpdf.annotate_member(page, "DEMO-0000")
            width, height = (440, 320) if rotation in (90, 270) else (320, 440)
            self.assertAlmostEqual(float(output.mediabox.width), width)
            self.assertAlmostEqual(float(output.mediabox.height), height + 14)
            self.assert_footer(output)

    def test_field_appearance_survives_matrix_offset_crop_and_rotation(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                page = self.form_page()
                writer = page.indirect_reference.pdf
                for reference in page["/Annots"]:
                    widget = reference.get_object()
                    x0, y0, x1, y1 = map(float, widget["/Rect"])
                    widget[NameObject("/Rect")] = RectangleObject((x0 + 100, y0 - 50, x1 + 100, y1 - 50))
                    # /AP can itself be indirect in an ordinary valid PDF.
                    widget[NameObject("/AP")] = writer._add_object(widget["/AP"])
                appearance = page["/Annots"][0].get_object()["/AP"]["/N"]
                appearance[NameObject("/Matrix")] = ArrayObject([FloatObject(v) for v in (2, 0, 0, 3, 17, -9)])
                page.add_transformation(Transformation().translate(tx=100, ty=-50))
                page.mediabox = RectangleObject((100, -50, 340, 290))
                page.cropbox = RectangleObject((120, -30, 320, 270))
                page.rotate(rotation)
                original_bytes = page.get_contents().get_data()
                output = healthpdf.annotate_member(page, "DEMO-0000")
                self.assertIn("THB 4,300.00", output.extract_text())
                self.assertFalse(output.get("/Annots"))
                self.assert_footer(output)
                self.assertEqual(page.rotation, rotation)
                self.assertEqual(page.get_contents().get_data(), original_bytes)
                self.assertEqual(len(page["/Annots"]), 2)
                self.assertEqual(list(page.cropbox), [120, -30, 320, 270])

    def test_missing_field_appearance_fails_without_removing_original_fields(self):
        page = self.form_page()
        widget = page["/Annots"][0].get_object()
        del widget["/AP"]
        with self.assertRaisesRegex(ValueError, "render a copy to a static PDF"):
            healthpdf.annotate_member(page, "DEMO-0000")
        self.assertEqual(widget["/V"], "THB 4,300.00")
        self.assertEqual(len(page["/Annots"]), 2)

    def test_hidden_fields_stay_hidden_and_no_rotate_requires_rendered_copy(self):
        for flags in (1, 2, 32):
            with self.subTest(flags=flags):
                page = self.form_page()
                page["/Annots"][0].get_object()[NameObject("/F")] = NumberObject(flags)
                output = healthpdf.annotate_member(page, "DEMO-0000")
                self.assertNotIn("THB 4,300.00", output.extract_text())
                self.assertFalse(output.get("/Annots"))
        page = self.form_page()
        page["/Annots"][0].get_object()[NameObject("/F")] = NumberObject(16)
        page.rotate(90)
        with self.assertRaisesRegex(ValueError, "render a copy"):
            healthpdf.annotate_member(page, "DEMO-0000")


if __name__ == "__main__":
    unittest.main()
