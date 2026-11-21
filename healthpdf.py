"""Portable claim packets for an assistant's Python environment. Python 3.10+."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, StreamObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import reportlab


ROOT = Path(__file__).resolve().parent
VERSION = "0.1.3"
CENT = Decimal("0.01")
FOOTER_HEIGHT = 14
STATIC_EVIDENCE_FALLBACK = (
    "An evidence form field cannot be made static without changing its appearance. "
    "The assistant should render a copy to a static PDF and visually check it; keep the original unchanged."
)
# ISO 4217 exceptions to two minor-unit decimal places. SIX List One, published
# 2026-09-17, verified 2026-11-21. USD output and EOB amounts remain cent-limited.
# https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml
CURRENCY_MINOR_UNITS = {
    **dict.fromkeys("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF".split(), 0),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    **dict.fromkeys("CLF UYW".split(), 4),
}
TRACKER_COLUMNS = [
    "claim_id", "patient", "provider", "service_date", "country", "currency",
    "original_amount", "submitted_usd", "fx_rate", "fx_date", "fx_source",
    "submission_status", "submitted_date", "insurer_claim_number", "eob_date",
    "insurer_paid_usd", "member_share_usd", "provider_receipt", "payment_proof",
    "eob_saved", "insurer_deposit_verified", "hsa_reimbursed", "notes",
]


def money(value, currency="USD"):
    """Preserve the original amount, validating its currency's minor-unit precision."""
    currency = str(currency).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Use a three-letter currency code")
    places = CURRENCY_MINOR_UNITS.get(currency, 2)
    quantum = Decimal(1).scaleb(-places)
    try:
        number = Decimal(str(value))
        valid = number.is_finite() and number >= 0 and number == number.quantize(quantum)
    except InvalidOperation as error:
        raise ValueError("Amount must be a number") from error
    if not valid:
        raise ValueError(f"Amount must be nonnegative and have at most {places} decimal places for {currency}")
    return number


def required(obj, key):
    value = obj.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"Please provide {key.replace('_', ' ')}")
    return value


def iso_date(value):
    return date.fromisoformat(str(value)).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def inventory(paths):
    result = []
    seen = {}
    for filename in paths:
        path = Path(filename)
        sha = digest(path)
        row = {"file": str(path), "sha256": sha, "bytes": path.stat().st_size}
        if sha in seen:
            row["duplicate_of"] = seen[sha]
        else:
            seen[sha] = str(path)
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(path)
            row["pages"] = len(reader.pages)
            row["text"] = [page.extract_text() or "" for page in reader.pages]
            row["needs_visual_reading"] = any(len(t.strip()) < 70 for t in row["text"])
        result.append(row)
    return result


def convert(amount, currency, service_date, fx=None):
    """Use supplied source-bound FX or look up date/currency metadata automatically."""
    currency = str(currency).strip().upper()
    amount = money(amount, currency)
    requested = iso_date(service_date)
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Use a three-letter currency code")
    if currency == "USD":
        return {"usd": str(amount.quantize(CENT)), "rate": "1", "date": requested, "source": "USD invoice"}
    if fx and "actual_usd" in fx:
        usd = money(fx["actual_usd"])
        if usd <= 0 or amount <= 0:
            raise ValueError("Use the positive documented USD payment for this expense")
        return {"usd": str(usd), "rate": str(usd / amount), "date": iso_date(required(fx, "date")),
                "source": str(required(fx, "source")), "method": "documented USD payment"}
    if fx is None:
        query = urlencode({"base": currency, "symbols": "USD"})
        url = f"https://api.frankfurter.dev/v1/{requested}?{query}"
        try:
            with urlopen(Request(url, headers={"User-Agent": "HealthPDF/0.1"}), timeout=20) as response:
                data = json.load(response)
            fx = {"usd_per_unit": data["rates"]["USD"], "date": data["date"], "source": url}
        except Exception as error:
            raise ValueError(
                "Rate lookup unavailable. The assistant can use web search to supply a cited "
                "historical USD-per-unit rate for the date of care and run this step again."
            ) from error
    rate = Decimal(str(required(fx, "usd_per_unit")))
    actual_date = iso_date(required(fx, "date"))
    source = str(required(fx, "source"))
    if not rate.is_finite() or rate <= 0 or actual_date > requested:
        raise ValueError("Use a positive rate dated on or before the service date")
    return {
        "usd": str((amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)),
        "rate": str(rate), "date": actual_date, "source": source,
    }


def font_name():
    if "HealthPDF" not in pdfmetrics.getRegisteredFontNames():
        path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
        pdfmetrics.registerFont(TTFont("HealthPDF", str(path)))
    return "HealthPDF"


def draw_text(pdf, value, rect):
    """Wrap measured text inside the actual form widget and reject clipping."""
    value = str(value)
    font = font_name()
    glyphs = pdfmetrics.getFont(font).face.charToGlyph
    if any(ord(ch) not in glyphs for ch in value if not ch.isspace()):
        raise ValueError("A form value needs an English transliteration or a font supporting its script")
    left, bottom, right, top = map(float, rect)
    width, height = right - left - 4, top - bottom - 3
    for size in (10, 9, 8, 7):
        words = value.split()
        lines = []
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if pdfmetrics.stringWidth(trial, font, size) <= width:
                line = trial
            else:
                if not line or pdfmetrics.stringWidth(word, font, size) > width:
                    lines = []
                    break
                lines.append(line)
                line = word
        else:
            if line:
                lines.append(line)
            if lines and len(lines) * size * 1.12 <= height:
                pdf.setFont(font, size)
                y = top - size - 1
                for line in lines:
                    pdf.drawString(left + 2, y, line)
                    y -= size * 1.12
                return
    raise ValueError(f"Form text will not fit legibly in this field: {value[:60]}")


def source_pdf(path):
    """Check source form settings before copying pages; fit photos on Letter pages."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        form = reader.trailer["/Root"].get("/AcroForm")
        form = form.get_object() if form is not None else None
        if isinstance(form, DictionaryObject):
            flag = form.get("/NeedAppearances", False)
            flag = flag.get_object() if hasattr(flag, "get_object") else flag
            # BooleanObject(False) is truthy as a Python object: use its stored value.
            if getattr(flag, "value", flag) and any(
                ref.get_object().get("/Subtype") == "/Widget"
                for page in reader.pages for ref in (page["/Annots"] if "/Annots" in page else [])
            ):
                raise ValueError("This evidence PDF needs its form fields redrawn. " + STATIC_EVIDENCE_FALLBACK)
        return reader
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
    except ImportError as error:
        if path.suffix.lower() in {".heic", ".heif", ".hif", ".heics", ".heifs"}:
            raise ValueError(
                "HEIC photos need pillow-heif. The assistant can install requirements.txt, "
                "or convert a copy to JPEG or PNG and keep the original unchanged."
            ) from error
    else:
        register_heif_opener(thumbnails=False)
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        if "A" in oriented.getbands() or "transparency" in oriented.info:
            rgba = oriented.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = oriented.convert("RGB")
        image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    photo = io.BytesIO()
    image.save(photo, format="JPEG", quality=95, optimize=True)
    photo.seek(0)
    width, height = 612, 792 - FOOTER_HEIGHT
    margin = 18
    scale = min((width - 2 * margin) / image.width, (height - 2 * margin) / image.height)
    drawn_width, drawn_height = image.width * scale, image.height * scale
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(width, height))
    pdf.drawImage(ImageReader(photo), (width - drawn_width) / 2, (height - drawn_height) / 2,
                  width=drawn_width, height=drawn_height)
    pdf.save()
    stream.seek(0)
    return PdfReader(stream)


def field_rect(entry, widgets, page_number):
    if isinstance(entry, str):
        return widgets.get(entry)
    if entry["page"] == page_number:
        return entry["rect"]
    return None


def flatten_template(template, spec, values, selected, corrected=False):
    reader = PdfReader(template)
    writer = PdfWriter()
    for page_number, source in enumerate(reader.pages):
        page = writer.add_page(source)
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
        widgets = {}
        for reference in page.get("/Annots", []):
            widget = reference.get_object()
            name = widget.get("/T")
            if name:
                widgets[str(name)] = list(widget["/Rect"])
        for key, field in spec["text"].items():
            rect = field_rect(field, widgets, page_number)
            if "mode.domestic" in selected and key in spec.get("overseas_only_text", []):
                continue
            if key in values and values[key] and rect:
                draw_text(pdf, values[key], rect)
        for key, field in spec["checkboxes"].items():
            rect = field_rect(field, widgets, page_number)
            if rect:
                x0, y0, x1, y1 = map(float, rect)
                pdf.setLineWidth(0.6)
                pdf.rect(x0, y0, x1 - x0, y1 - y0)
                if key in selected:
                    pdf.setLineWidth(1)
                    pdf.line(x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5)
                    pdf.line(x0 + 1.5, y1 - 1.5, x1 - 1.5, y0 + 1.5)
        if corrected and page_number == 0:
            pdf.setFont(font_name(), 8)
            pdf.drawString(36, 14, "UPDATED/CORRECTED from earlier submission")
        pdf.showPage()
        pdf.save()
        if "/Annots" in page:
            del page["/Annots"]
        page.merge_page(PdfReader(stream).pages[0])
    return writer


def flatten_evidence_widgets(page):
    """Paint existing field appearances into a writer-owned page, then remove widgets."""
    widgets = [ref.get_object() for ref in page.get("/Annots", [])
               if ref.get_object().get("/Subtype") == "/Widget"]
    if not widgets:
        return
    fallback = STATIC_EVIDENCE_FALLBACK
    resources = page.setdefault(NameObject("/Resources"), DictionaryObject()).get_object()
    resources.setdefault(NameObject("/XObject"), DictionaryObject())
    xobjects = resources["/XObject"]
    commands = []
    for widget in widgets:
        flags = int(widget.get("/F", 0))
        if flags & 35:  # Invisible, Hidden and NoView fields are not displayed evidence.
            continue
        if flags & 16 and page.rotation:  # NoRotate needs the viewer's annotation layout.
            raise ValueError(fallback)
        appearance = widget.get("/AP")
        appearance = appearance.get_object() if appearance is not None else None
        if not isinstance(appearance, DictionaryObject):
            raise ValueError(fallback)
        normal = appearance.get("/N")
        normal = normal.get_object() if normal is not None else None
        if isinstance(normal, DictionaryObject) and not isinstance(normal, StreamObject):
            state, parent = widget.get("/AS"), widget
            while state is None and parent is not None:
                state = parent.get("/V")
                parent = parent["/Parent"] if "/Parent" in parent else None
            normal = normal.get(state or "/Off")
            normal = normal.get_object() if normal is not None else None
        if not isinstance(normal, StreamObject) or getattr(normal, "indirect_reference", None) is None or "/BBox" not in normal:
            raise ValueError(fallback)
        left, bottom, right, top = map(float, widget["/Rect"])
        bx0, by0, bx1, by1 = map(float, normal["/BBox"])
        matrix = Transformation(tuple(map(float, normal.get("/Matrix", (1, 0, 0, 1, 0, 0)))))
        corners = [matrix.apply_on(point) for point in ((bx0, by0), (bx0, by1), (bx1, by0), (bx1, by1))]
        x0, y0 = min(p[0] for p in corners), min(p[1] for p in corners)
        x1, y1 = max(p[0] for p in corners), max(p[1] for p in corners)
        if not all(isfinite(v) for v in (left, bottom, right, top, x0, y0, x1, y1)) or right <= left or top <= bottom or x1 <= x0 or y1 <= y0:
            raise ValueError(fallback)
        sx, sy = (right - left) / (x1 - x0), (top - bottom) / (y1 - y0)
        transform = (sx, 0, 0, sy, left - sx * x0, bottom - sy * y0)
        if not all(isfinite(v) for v in transform):
            raise ValueError(fallback)
        name = "/HealthPDFField" + str(len(xobjects))
        while name in xobjects:
            name += "_"
        xobjects[NameObject(name)] = normal.indirect_reference
        coordinates = " ".join(f"{v:.10f}".rstrip("0").rstrip(".") or "0" for v in transform)
        commands.append(f"q\n{coordinates} cm\n{name} Do\nQ\n".encode("ascii"))
    if commands:
        original = page.get_contents()
        stream = DecodedStreamObject()
        stream.set_data(b"q\n" + (original.get_data() if original is not None else b"") + b"\nQ\n" + b"".join(commands))
        page.replace_contents(stream.flate_encode())
    remaining = [ref for ref in page.get("/Annots", []) if ref.get_object().get("/Subtype") != "/Widget"]
    if remaining:
        page[NameObject("/Annots")] = ArrayObject(remaining)
    else:
        del page["/Annots"]


def annotate_member(page, member_id):
    """Keep the displayed crop/orientation and add an upright footer outside it."""
    # Work on writer-owned copies so rotation/merging cannot alter the source reader.
    working = PdfWriter()
    source = working.add_page(page)
    flatten_evidence_widgets(source)
    if source.rotation:
        source.transfer_rotation_to_content()
    left, bottom, right, top = map(float, source.cropbox)
    unit = float(source.user_unit)
    if not all(isfinite(v) for v in (left, bottom, right, top, unit)) or right <= left or top <= bottom or unit <= 0:
        raise ValueError("The evidence page has invalid visible page bounds")
    width, height = (right - left) * unit, (top - bottom) * unit
    output = working.add_blank_page(width=width, height=height + FOOTER_HEIGHT)
    output.merge_transformed_page(
        source, Transformation().scale(sx=unit, sy=unit).translate(tx=-left * unit, ty=FOOTER_HEIGHT - bottom * unit)
    )
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(width, height + FOOTER_HEIGHT))
    pdf.setFont(font_name(), 7)
    pdf.drawString(12, 3, "Member ID " + member_id)
    pdf.save()
    output.merge_page(PdfReader(stream).pages[0])
    return output


def validate_claim(profile, claim, spec):
    subscriber = required(profile, "subscriber")
    for key in spec.get("required_subscriber", ["name", "member_id", "plan_name", "group_number"]):
        required(subscriber, key)
    if not (subscriber.get("phone") or subscriber.get("email")):
        raise ValueError("Please provide the subscriber's phone number or email")
    matches = [p for p in profile.get("patients", []) if p.get("id") == required(claim, "patient_id")]
    if len(matches) != 1:
        raise ValueError("Select exactly one patient from the household profile")
    patient = matches[0]
    required(patient, "name")
    iso_date(required(patient, "dob"))
    iso_date(required(claim, "date_of_service"))
    country = str(required(claim, "service_country"))
    domestic = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA", "PUERTO RICO", "PR", "GUAM", "GU",
                "US VIRGIN ISLANDS", "U.S. VIRGIN ISLANDS", "VI", "AMERICAN SAMOA", "AS", "NORTHERN MARIANA ISLANDS", "MP"}
    mode = "domestic" if country.strip().upper() in domestic else "overseas"
    provider = required(claim, "provider")
    required(provider, "name")
    required(provider, "address")
    if mode == "domestic" and spec.get("requires_us_tax_id", True) and not re.fullmatch(r"\d{9}", str(provider.get("tax_id", ""))):
        raise ValueError("Please provide the U.S. provider's nine-digit tax ID from its bill")
    required(claim, "diagnosis")
    amount = required(claim, "amount")
    if money(required(amount, "total"), required(amount, "currency")) <= 0:
        raise ValueError("Use the positive final invoice total after discounts")
    services = required(claim, "services")
    if not isinstance(services, list) or not services:
        raise ValueError("Select the service types supported by the receipt")
    for service in services:
        if mode + "." + str(service) not in spec["checkboxes"]:
            raise ValueError(f"Unsupported {mode} service type {service}. Use other with a description.")
    if "other" in services:
        required(claim, "description")
    if claim.get("kind", "new") not in {"new", "correction"}:
        raise ValueError("Use new or correction for the claim kind")
    evidence = required(claim, "evidence")
    if not any(e.get("role") == "receipt" for e in evidence):
        raise ValueError("Please attach the itemized invoice or receipt")
    if claim.get("kind") == "correction":
        required(claim, "prior_claim_number")
        if not any(e.get("role") == "prior_eob" for e in evidence):
            raise ValueError("Please attach the prior EOB for the corrected claim")
    for e in evidence:
        if e.get("role") not in {"receipt", "certificate", "translation", "payment_proof", "prior_eob"}:
            raise ValueError("Use a supported evidence role")
        if not Path(required(e, "path")).is_file():
            raise ValueError("An evidence file is unavailable: " + str(e["path"]))
    if patient["dob"] > claim["date_of_service"]:
        raise ValueError("The patient's birth date is later than the date of care")
    return subscriber, patient, provider, mode


def make_packet(profile, claim, output, progress=None):
    """Create a flattened claim, evidence packet, email, tracker and portable progress."""
    spec_file = Path(claim.get("template_spec", ROOT / "templates/geha.json")).resolve()
    spec = json.loads(spec_file.read_text())
    template = (spec_file.parent / spec["template"]).resolve()
    if digest(template) != spec["sha256"]:
        raise ValueError("The template changed. Inspect and update its field mapping before filling it.")
    subscriber, patient, provider, mode = validate_claim(profile, claim, spec)
    converted = convert(claim["amount"]["total"], claim["amount"]["currency"], claim["date_of_service"], claim.get("fx"))
    dob = date.fromisoformat(patient["dob"])
    service_date = date.fromisoformat(claim["date_of_service"])
    values = {
        "plan_name": subscriber.get("plan_name", ""), "group_number": subscriber.get("group_number", ""),
        "subscriber": subscriber["name"], "member_id": subscriber["member_id"],
        "patient": patient["name"], "contact": " / ".join(filter(None, [subscriber.get("phone"), subscriber.get("email")])),
        "dob_month": dob.strftime("%m"), "dob_day": dob.strftime("%d"), "dob_year": dob.strftime("%Y"),
        "date_month": service_date.strftime("%m"), "date_day": service_date.strftime("%d"), "date_year": service_date.strftime("%Y"),
        "facility": provider.get("facility", provider["name"]), "provider": provider["name"],
        "tax_id": provider.get("tax_id", "") if mode == "domestic" else "", "provider_address": provider["address"],
        "country": claim["service_country"], "usd": converted["usd"], "diagnosis": claim["diagnosis"],
        "description": claim.get("description", ""),
    }
    selected = {mode + "." + service for service in claim["services"]}
    selected.add("payment." + claim.get("pay_to", "member"))
    selected.add("mode." + mode)
    if not selected.issubset(spec["checkboxes"]):
        raise ValueError("Use member or provider for the payee")
    mapped = {value for value in list(spec["text"].values()) + list(spec["checkboxes"].values()) if isinstance(value, str)}
    if not mapped.issubset(PdfReader(template).get_fields() or {}):
        raise ValueError("The template fields do not match the tested mapping")
    corrected = claim.get("kind") == "correction"
    writer = flatten_template(template, spec, values, selected, corrected)
    seen = set()
    evidence_manifest = []
    priorities = {"receipt": 0, "certificate": 1, "translation": 2, "payment_proof": 3, "prior_eob": 4}
    for e in sorted(claim["evidence"], key=lambda e: priorities[e["role"]]):
        sha = digest(e["path"])
        if sha in seen:
            continue
        seen.add(sha)
        reader = source_pdf(e["path"])
        start = len(writer.pages) + 1
        for page in reader.pages:
            writer.add_page(annotate_member(page, subscriber["member_id"]))
        evidence_manifest.append({"file": Path(e["path"]).name, "role": e["role"], "sha256": sha, "pages": [start, len(writer.pages)]})
    target = Path(output).resolve()
    if target.exists():
        raise ValueError("Choose a new output folder for this version")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".healthpdf-", dir=target.parent))
    try:
        with (stage / "claim-packet.pdf").open("wb") as f:
            writer.write(f)
        claim_id = str(claim.get("id") or hashlib.sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()[:16])
        currency = claim["amount"]["currency"].strip().upper()
        amount = str(money(claim["amount"]["total"], currency))
        opening = (f"I am resubmitting corrected information for claim {claim['prior_claim_number']}." if corrected
                   else "Please process the attached medical claim.")
        subject = ("Corrected claim " + claim["prior_claim_number"] if corrected else "Medical claim") + " - " + patient["name"] + " - " + claim["date_of_service"]
        email = f"""To: {profile.get('insurer', {}).get('claim_email', spec['claim_email'])}
Subject: {subject}

Dear Claims Team,

{opening} The patient is {patient['name']}, treated by {provider['name']} on {claim['date_of_service']}.

The final charge is {amount} {currency}. The packet includes the completed claim form and supporting documents."""
        if converted.get("method") == "documented USD payment":
            email += f" The documented USD payment is ${converted['usd']}."
        elif currency != "USD":
            email += f" The USD equivalent shown is ${converted['usd']} using the recorded date-of-care conversion."
        if corrected:
            email += " The earlier EOB is included at the end for reference."
        email += f"\n\nThank you,\n{subscriber['name']}\nMember ID {subscriber['member_id']}\n"
        (stage / "email-draft.txt").write_text(email)
        write_json(stage / "profile.json", profile)
        tracker = {key: "" for key in TRACKER_COLUMNS}
        tracker.update(claim_id=claim_id, patient=patient["name"], provider=provider["name"], service_date=claim["date_of_service"],
                       country=claim["service_country"], currency=currency, original_amount=amount, submitted_usd=converted["usd"],
                       fx_rate=converted["rate"], fx_date=converted["date"], fx_source=converted["source"], submission_status="prepared",
                       provider_receipt="yes", payment_proof="yes" if any(e["role"] == "payment_proof" for e in evidence_manifest) else "unknown",
                       hsa_reimbursed="no", notes="Review the completed PDF before submitting.")
        previous = json.loads(json.dumps(progress or {}))
        claims = previous.get("claims", [])
        matches = [row for row in claims if row["claim_id"] == claim_id]
        if len(matches) > 1:
            raise ValueError("The saved progress contains duplicate claim IDs")
        history = previous.get("history", [])
        if matches:
            history.append({"claim": matches[0], "replaced_by": claim_id})
            old = matches[0]
            for key in ("submitted_date", "insurer_claim_number", "eob_date", "insurer_paid_usd", "member_share_usd",
                        "eob_saved", "insurer_deposit_verified", "hsa_reimbursed"):
                tracker[key] = old.get(key, "")
            if old.get("payment_proof") == "yes":
                tracker["payment_proof"] = "yes"
            tracker["notes"] = (old.get("notes", "") + " " + tracker["notes"]).strip()
        if corrected:
            tracker["insurer_claim_number"] = claim["prior_claim_number"]
            tracker["submission_status"] = "correction_prepared"
        claims = [row for row in claims if row["claim_id"] != claim_id] + [tracker]
        save_tracker(stage / "tracker.csv", claims)
        packets = previous.get("packets", [])
        packets.append({"claim_id": claim_id, "packet_sha256": digest(stage / "claim-packet.pdf"),
                        "evidence": evidence_manifest, "fx": converted, "visual_check": "pending"})
        saved_progress = {**previous, "version": VERSION, "profile": profile, "claims": claims, "history": history,
                          "packets": packets}
        write_json(stage / "progress.json", saved_progress)
        (stage / "review.txt").write_text(
            "Open claim-packet.pdf and check patient, date, provider, amounts, checkboxes and evidence pages.\n"
            "The assistant must render and inspect the form before calling the packet ready to submit.\n"
            "Report submitted only after you confirm sending. Keep progress.json privately for the next conversation.\n"
        )
        stage.rename(target)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {"folder": str(target), "claim_id": claim_id, "packet": str(target / "claim-packet.pdf"), "fx": converted}


def save_tracker(path, rows):
    with Path(path).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalized_patient_name(value):
    """Normalize presentation only; never guess initials, omit names or use fuzzy matching."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    parts = value.split(",")
    if len(parts) == 2 and all(part.strip() for part in parts):
        value = parts[1] + " " + parts[0]
    return " ".join(value.split())


def reconcile(tracker, eob):
    """Bind an EOB to an exact local claim ID, preserving independent proof facts."""
    with Path(tracker).open(newline="") as source:
        rows = list(csv.DictReader(source))
    matches = [r for r in rows if r["claim_id"] == required(eob, "claim_id")]
    if len(matches) != 1:
        raise ValueError("Match the EOB to exactly one claim in the tracker")
    row = matches[0]
    if (normalized_patient_name(row["patient"]) != normalized_patient_name(required(eob, "patient"))
            or row["service_date"] != iso_date(required(eob, "service_date"))):
        raise ValueError("EOB patient or service date conflicts with this claim")
    if eob.get("provider") and row["provider"] != eob["provider"]:
        raise ValueError("EOB provider differs. Confirm its documented billing alias before matching.")
    paid = money(required(eob, "paid_usd"))
    member = money(required(eob, "member_share_usd"))
    billed = money(required(eob, "billed_usd"))
    discounts = money(eob.get("discount_usd", "0"))
    if paid + member + discounts != billed:
        raise ValueError("The EOB totals need review before updating this claim")
    status = required(eob, "status")
    if status not in {"paid", "partially_paid", "denied", "needs_information"}:
        raise ValueError("Use the documented EOB disposition")
    claim_number = str(required(eob, "insurer_claim_number"))
    notice = iso_date(required(eob, "notice_date"))
    eob_file = Path(required(eob, "path"))
    if not eob_file.is_file():
        raise ValueError("Keep the EOB PDF with the claim before marking it saved")
    fingerprint = digest(eob_file)
    entry = f"EOB {claim_number} dated {notice}, SHA256 {fingerprint}. " + str(eob.get("reason", ""))
    if entry not in row.get("notes", ""):
        row["notes"] = (row.get("notes", "") + " " + entry).strip()
    row.update(insurer_claim_number=claim_number, eob_date=notice, insurer_paid_usd=str(paid),
               member_share_usd=str(member), eob_saved="yes", submission_status=status)
    return rows


def save_reconciled_progress(path, rows, eob, previous=None):
    progress = json.loads(json.dumps(previous or {}))
    progress.update(version=VERSION, claims=rows)
    events = progress.setdefault("eobs", [])
    record = {**eob, "path": Path(eob["path"]).name, "sha256": digest(eob["path"])}
    if not any(event.get("sha256") == record["sha256"] and event.get("claim_id") == record["claim_id"] for event in events):
        events.append(record)
    write_json(path, progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("inventory")
    p.add_argument("files", nargs="+")
    p = commands.add_parser("convert")
    p.add_argument("amount")
    p.add_argument("currency")
    p.add_argument("date")
    p = commands.add_parser("prepare")
    p.add_argument("--profile", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--progress", help="Saved progress.json from an earlier batch")
    p = commands.add_parser("reconcile")
    p.add_argument("--tracker", required=True)
    p.add_argument("--eob", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--progress", help="Existing progress.json to retain all claim history")
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            result = inventory(args.files)
        elif args.command == "convert":
            result = convert(args.amount, args.currency, args.date)
        elif args.command == "prepare":
            result = make_packet(json.loads(Path(args.profile).read_text()), json.loads(Path(args.claim).read_text()), args.out,
                                 json.loads(Path(args.progress).read_text()) if args.progress else None)
        else:
            eob = json.loads(Path(args.eob).read_text())
            result = reconcile(args.tracker, eob)
            progress_file = Path(args.out).with_suffix(".progress.json")
            if Path(args.out).exists() or progress_file.exists():
                raise ValueError("Choose a new tracker filename for this revision")
            save_tracker(args.out, result)
            previous = json.loads(Path(args.progress).read_text()) if args.progress else None
            save_reconciled_progress(progress_file, result, eob, previous)
            result = {"tracker": args.out, "progress": str(progress_file), "records": len(result)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
