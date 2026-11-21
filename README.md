# HealthPDF

HealthPDF helps your AI chatbot prepare GEHA insurance claims from your receipts and invoices. **You do not need GitHub, Codex, or programming knowledge—just your usual AI chatbot.**

## Start here

1. [Download the HealthPDF starter kit](https://github.com/guynod/GEHA-HealthPDF/raw/refs/heads/main/healthpdf-starter.zip).
2. Start a new conversation in **ChatGPT, Gemini, or Claude**.
3. Attach the downloaded ZIP and your medical receipts or invoices.
4. Copy and paste this message:

```text
Use the attached HealthPDF kit. Read START-HERE.md and ASSISTANT-GUIDE.md,
then prepare my insurance claim. Get information from my documents first
and ask me together for anything missing. Infer the service country and
currency from the invoice, handle currency conversion, and give me a
completed claim PDF, an email draft, and the tracking files to save for
next time.
```

The chatbot will ask for your insurance and household details when needed. Check the completed claim before submitting it yourself.

If it cannot open the ZIP, unzip it and attach the files inside. If it cannot create downloadable PDFs, you’ll need a chatbot version that supports file creation.

Keep your completed files privately for your next claim. Never upload personal medical or insurance information to this GitHub repository.

For app settings and troubleshooting, see [assistant setup](docs/assistant-setup.md).

## What you receive

Upload PDFs or phone photos, including JPEG, PNG, and iPhone HEIC/HEIF files. HealthPDF prepares readable Letter-sized photo pages while keeping your originals unchanged.

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
