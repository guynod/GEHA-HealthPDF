# Start HealthPDF

Upload this kit and the receipts, invoices, or EOBs you want to process. Then send the following message.

```text
Use HealthPDF to prepare or reconcile my insurance claims. Read the attached
ASSISTANT-GUIDE.md and use the shared PDF helper when code execution is available.
Start with the documents I have supplied. Extract information already visible
on those documents, and ask me one short group of questions for missing details.
Save my answers in a reusable private profile. Proceed with routine currency
conversion, arithmetic, document assembly, and tracker updates. Return the
completed PDF packet, email draft, tracker, and progress file for me to review.
```

## The first questions

The assistant should ask for any of these details it cannot read from your uploaded documents.

- Insurer, exact plan name, plan group number, and member or policy number.
- Subscriber’s legal name, mailing address, email address, and phone number.
- Patient’s legal name, date of birth, and relationship to the subscriber.
- For another household member, their name, date of birth, and relationship when first needed.
- Other insurance details when the form asks for them.

Dates of birth should be written with the month spelled out, or as `YYYY-MM-DD`, to avoid confusion between day and month. The assistant will format them for the insurer.

The assistant should obtain the provider name, address, service dates, services, diagnosis or reason for care, and charges from your receipts and supporting documents. It should infer service country and currency from the invoice’s address, currency labels, symbols, and payment details, then choose the form section automatically. A Bangkok provider address with baht charges normally establishes Thailand, THB, and overseas service. A Hong Kong clinic invoice marked HKD establishes Hong Kong and HKD. If a required fact is missing or contradictory, it should ask about that fact.

## After the first batch

You can use short requests once setup is complete.

```text
Run HealthPDF on this.
```

```text
Reconcile these EOBs against my attached tracker and progress file. Update my
saved files and tell me what changed and what evidence is still missing.
```

Download and keep the completed packet, email draft, `profile.json`, the latest tracker, and its matching progress file. Packet generation produces `tracker.csv` and `progress.json`. An EOB update may produce names such as `tracker-updated.csv` and `tracker-updated.progress.json`. Keep the newest pair together. These files let you continue with another assistant or a new conversation.

For your next batch, upload the saved profile, tracker, and progress file with the new documents, then send this message.

```text
Continue HealthPDF from my saved files. Process the new documents, avoid
duplicates, and update the tracker. Ask only about missing information that
affects the claim. Give me the completed files to review.
```

## Corrected claims

Upload the updated invoice and the earlier insurer EOB or request for information. Say what changed. HealthPDF should match the earlier claim, put **UPDATED/CORRECTED from earlier submission** at the bottom of the revised form, and include the earlier EOB at the end of the packet.

## Currency conversion

HealthPDF proceeds automatically. It uses the actual documented USD payment when available. Otherwise it obtains a dated public exchange rate, records the source and rate date, and retains the original currency and amount. If the service date falls on a non-business day, it records the date of the available rate used. The insurer may apply its own conversion.

## Review and submit

Review the completed form and its attachments together. Sign when the actual form requires it. The bundled GEHA form has no signature line. Submit the packet through your insurer’s current filing channel, then tell the assistant when you submitted it so the tracker reflects what happened.
