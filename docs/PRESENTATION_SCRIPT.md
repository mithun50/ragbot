# RagBot presentation script

Tagline: **Answers, with receipts.**
Demo link: http://localhost:8001 . Demo file: `samples/helios_handbook.pdf` (269 pages, 146,632 words, 893,096 characters).

## 1. The problem (30 seconds)
"Everyone has a document they will never fully read: a handbook, a contract, a policy. Normal chatbots fail in two ways. They cannot hold a 300 page file, and when they guess, you cannot tell. RagBot fixes both. It reads documents of any size, and every answer comes with a receipt: the exact page and passage it came from."

## 2. What we built (20 seconds)
"RagBot is a document question answering assistant. You upload one or more files, then chat. It answers only from your documents, cites every claim, and says 'not found' when the answer is not there."

## 3. Live demo (3 minutes)
1. **Upload.** Drag in the handbook. "Pages are processed one at a time, so a 1000 page PDF behaves like a 10 page one. This took about 3 seconds for 269 pages."
2. **Ask.** Type: "What is the minimum voltage the battery bus can be discharged to on Helios-C?" Point at the live steps: searching, ranking, reading, writing. "Nothing is hidden."
3. **Receipts.** Answer: 31.5 volts. Click the citation chip: the source panel opens on page 62 with the matching words highlighted. "The document also has a decoy, 26.8 volts for another spacecraft on page 181. It picks the right one."
4. **Follow up** in the same chat: "And what about Helios-A?" "One chat, any number of documents, no re-uploading."
5. **Refusal.** Ask: "What is the CEO's salary?" It says plainly that the document does not state it, and shows what it does cover. "It does not guess, and it does not even call the model."
6. **Voice.** Click the mic and ask a question out loud (Chrome or Edge).
7. **Analytics tab.** Questions, answer rate, time to first token, tokens in and out, cache hit rate.

## 4. How the RAG works (2 minutes, read the diagram top to bottom)
Open the architecture diagram on the welcome screen and press Expand.

"We use **advanced, modular RAG** with keyword retrieval. RAG means retrieval augmented generation: find the right passages first, then let the model answer from only those.

1. **Ingestion.** The file is parsed page by page, cut into chunks of about 180 words with overlap, and added to an inverted index.
2. **Cache.** If we have answered this exact question over these documents, we replay it in about 1 millisecond for zero tokens.
3. **Query expansion.** The question becomes three searches by keeping its key terms and boosting numbers and quoted phrases.
4. **BM25 retrieval.** Each search scores the chunks in about half a millisecond.
5. **Rank fusion.** Reciprocal rank fusion merges the three result lists into one.
6. **Relevance gate.** If the best match is too weak, we stop and answer 'not found'. This is our protection against hallucination.
7. **Diversify and expand.** MMR keeps 7 distinct passages, and we attach neighbouring text so answers that cross a chunk boundary still work.
8. **Grounded generation.** The model sees only numbered passages and must cite them, or reply NOT_FOUND.
9. **Citation check.** Any citation that is not one of the retrieved passages is thrown away."

"The model always sees about 7 passages, so speed and cost stay flat whether the file has 5 pages or 5,000."

## 5. Proof (30 seconds)
"We tested 25 planted facts in a 269 page document, including near-duplicate decoys. The right passage was in the top results for 24 of 25 questions, 96 percent. Search takes about half a millisecond."

## 6. Honest limits and next step (30 seconds)
"Today retrieval is keyword based, which is exact on names, numbers and IDs but does not match synonyms. Our next module is dense embeddings, fused with BM25 using the same rank fusion step, which makes it full hybrid RAG. The design is modular, so that is a drop in change. We run on free models, so a long answer can take about 10 to 15 seconds. A paid key makes it near instant, and repeat questions are already instant from the cache."

## Close
"RagBot. Any size document, every answer cited, and it says so when it does not know. Answers, with receipts."

## If asked
- **Is it vector RAG?** No. It is sparse retrieval with query expansion, fusion, re-ranking and a refusal gate. Dense retrieval is the planned upgrade.
- **Why not just paste the document into the model?** Context limits, cost, speed, and no proof of where an answer came from.
- **What stops hallucination?** The relevance gate, a strict grounding prompt, and citation validation.
- **Does it scale?** Streaming ingestion with bounded memory, an inverted index, and constant size prompts.
