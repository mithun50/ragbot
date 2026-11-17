# RagBot demo script (10 minutes)

Tagline: **Answers, with receipts.**

Before you go on stage: server running at http://localhost:8000, `samples/helios_handbook.pdf` ready to drag in, microphone allowed in Chrome, dark and light theme both checked.

## 0:00 to 1:00 - The problem
"Everyone has a document they will never fully read. A 300 page handbook, a contract, a policy. Chatbots can talk about anything, but they cannot read your 300 pages, and when they guess, you cannot tell. Two failures: they cannot hold the document, and they cannot prove their answer."

"RagBot fixes both. It reads documents of any size, and every answer comes with a receipt: the exact page and passage."

## 1:00 to 2:30 - Upload a big document
1. Drag `helios_handbook.pdf` (about 300 pages) into the sidebar.
2. While the progress bar runs: "It parses page by page and never loads the whole file into memory, so a 1000 page PDF behaves the same as a 10 page one."
3. When it is ready, point at the summary, key facts, and three suggested questions: "It reads first, so you do not have to know what to ask."

## 2:30 to 5:00 - Ask, and watch it work
1. Click a suggested question. Narrate the live steps: "Searching, ranking, reading passages, writing the answer. Nothing is hidden."
2. Point at the answer: "Every claim has a citation chip." Click a chip: the source panel opens on the exact page with the matching words highlighted.
3. Point at the metrics row: "Time to first token, total time, tokens in and out, tokens per second, and which model answered."
4. Ask a precise question, for example: "What is the minimum voltage the battery bus can be discharged to?" (answer: 31.5 volts). "This is a needle in a 300 page haystack. The document also contains near-duplicate numbers in other chapters as decoys, and it picks the right one."
5. Ask the same question again: "Cache hit, answered in about a millisecond, zero tokens spent."

## 5:00 to 6:00 - Voice
Click the mic and ask a question out loud: "Which ground station handles contacts in the early morning?" Text appears live and sends itself. "Hands free, same receipts."

## 6:00 to 7:00 - It refuses to guess
Ask: "What is the CEO's salary?" It answers that the passages do not state it, and lists what the document does cover, with citations. "This is the part that matters. When the answer is not in the document, it says so. No hallucination, and it does not even call the model, so it is instant and free."

## 7:00 to 8:00 - Multi document
Drag in `policy_short.docx`. Ask a question that only the policy answers. "Each citation names its file. You can include or exclude documents from the search with one click."

## 8:00 to 9:00 - Analytics
Open the Analytics tab. "Questions asked, answer rate, not found rate, average time to first token, p95 latency, cache hit rate, tokens in and out, which documents get used. This is how a team would see whether the assistant is trusted and where documents are missing answers."

## 9:00 to 10:00 - How it works and close
Show the architecture diagram (docs/ARCHITECTURE.md).
"Advanced, modular RAG: sparse BM25 retrieval over an inverted index, query expansion, reciprocal rank fusion, then MMR so the passages are diverse, and neighbour expansion so answers that cross a chunk boundary still work. The model only ever sees about 7 passages, so cost and speed do not grow with document size. A strict prompt forces citations and NOT_FOUND when the context is silent."

Close: "RagBot. Answers, with receipts."

## If something goes wrong
- Model slow or rate limited: the free tier can be slow. Say "free tier model, a paid key makes this near instant", and show the cache hit.
- Mic blocked: click the lock icon in the address bar, allow the microphone, retry.
- Backup: keep a screen recording of a clean run.
