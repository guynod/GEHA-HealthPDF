# Choose your assistant

Use a session that can read uploaded files, execute Python, and return downloadable files. The same HealthPDF starter kit is used in each app. Account settings and available tools can vary.

## ChatGPT

Start a conversation with file uploads and data analysis available. Upload the kit and your documents, then paste the start message from `START-HERE.md`. Ask ChatGPT to unpack the kit and run its PDF helper. If archive upload is unavailable, unzip it on your device and attach the individual files.

OpenAI documents [file uploads](https://help.openai.com/en/articles/8555545-uploading-files-and-audio-to-chatgpt) and [data analysis](https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt). A successful upload alone does not confirm that the selected chat can execute code or produce files.

## Claude

Start a conversation with code execution and file creation available. If needed, check **Settings → Capabilities** for **Create and edit files** or **Code execution and file creation**. Upload the kit and documents and paste the same start message.

Anthropic explains the available settings and download workflow in [Create and edit files with Claude](https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude).

## Gemini

Upload the kit and documents in a Gemini conversation with file creation available, then paste the same start message. When your session supports generated tasks and files, ask Gemini to execute the supplied helper and return the finished PDF and tracker. If a ZIP is rejected or its file count exceeds your account’s limit, unzip it and attach the instruction file, helper, form and mapping first, then add receipts in batches.

Google documents [uploading files](https://support.google.com/gemini/answer/14903178) and [working with generated files](https://support.google.com/gemini/answer/17094507). Code reasoning, Canvas output, and an executable file environment can have different availability. Ask Gemini to confirm that it created an actual downloadable PDF before treating a packet as complete.

## Continue later

Download the finished packet, `profile.json`, and the newest matching tracker and progress files. After EOB reconciliation, those might be named `tracker-updated.csv` and `tracker-updated.progress.json`. In a new conversation, upload the kit, profile, newest matching pair, and the new receipts or EOBs. This also lets you move between assistants.

## If something fails

Ask the assistant to state the specific missing tool or unreadable page, save completed work, and continue with other usable documents. A clearer scan may resolve unreadable evidence. For file-generation limitations, use a session with working code execution and downloads. Review the final PDF on your device before submission.
