# HealthPDF

Prepare insurance claim packets and reconcile EOBs in ChatGPT, Gemini, or Claude. Start with receipts and download a completed PDF, an email draft, and a simple claims tracker.

## Start in three steps

1. Download and unzip `healthpdf-starter.zip` from this repository.
2. Start a new conversation in your preferred assistant. Attach the starter ZIP and your receipts. If the assistant cannot open the ZIP, attach its individual files instead.
3. Paste this message.

```text
Use the attached HealthPDF kit. Read START-HERE.md and ASSISTANT-GUIDE.md,
then help me prepare these claims. Ask for my household and insurance details
once, using information already present in my documents. Complete routine
calculations, currency conversion, PDF preparation, and tracker updates without
asking me to approve each step. Give me the finished packet and email to review.
```

Your assistant will ask for the subscriber and patient details needed by the form. After the first claim, save the downloaded `profile.json`, `progress.json`, and `tracker.csv` privately. Upload them with the next batch to continue.

For app settings and troubleshooting, see [assistant setup](docs/assistant-setup.md).

## What you receive

- A completed claim form with the receipts and supporting documents attached.
- A short email draft ready for your review and manual submission.
- A CSV tracker that opens in Excel, Numbers, or Google Sheets.
- A progress file identifying filed evidence, unresolved questions, and claim history.

You can also upload EOBs and ask HealthPDF to reconcile them against your saved tracker. For a corrected submission, include the earlier EOB and the corrected invoice. The packet will put the corrected form first, followed by the supporting evidence and earlier EOB.

## GEHA forms included

The current GEHA Member Claim Submission Form supports both domestic and overseas medical claims. GEHA links to the same two-page form from its domestic and overseas guidance. HealthPDF reads the provider location and selects the appropriate section automatically. It also identifies the currency from the invoice and payment evidence.

The original blank form is [GEHA-Member-Claim-Submission.pdf](templates/GEHA-Member-Claim-Submission.pdf). Its printed revision is **UMF0022-GEHA 1025 UA**. The bundled packet helper has a GEHA mapping. For another insurer, upload its current form and instructions so the assistant can inspect its fields and prepare a matching form.

See GEHA’s [claims guidance](https://www.geha.com/membership/claims), [overseas guidance](https://www.geha.com/resource-center/medical-member-resources/outside-the-united-states), and [official form](https://www.mygeha.com/print/UMF0022-GEHA.pdf).

## Works across assistants

The same instructions, data files, and Python helper are used in all three assistants. PDF generation requires an assistant session with working code execution and downloadable file creation. App availability and upload limits depend on the account and workspace. The setup guide explains how to check those capabilities.

## Your documents

Keep personal profiles, insurance cards, medical records, statements, and generated packets in your own private files. Uploading them to an assistant shares them with that service under your account’s data settings. This repository contains reusable instructions, blank templates, and fictional examples.

The final packet is for your review before you submit it. Read the names, dates, amounts, service descriptions, and selected boxes. Sign only when the actual form requires a signature. The bundled GEHA form has no signature line.

## For people maintaining the kit

`ASSISTANT-GUIDE.md` defines the workflow. `healthpdf.py` provides the shared calculations and PDF helpers. `templates/geha.json` maps the bundled GEHA form. Run the included checks after changing a form or mapping, and visually inspect both domestic and overseas sample packets.

GEHA’s form remains the property of its publisher. This project is an independent document-preparation aid.
