# RagBot architecture

## System overview
```mermaid
flowchart LR
    U[User: text or voice] --> FE[Web app: chat, sources, analytics]
    FE -->|upload| API[FastAPI]
    FE -->|ask via SSE stream| API
    API --> ING[Ingestion pipeline]
    API --> QA[QA engine]
    ING --> STORE[(Index store: chunks and inverted index)]
    QA --> STORE
    QA --> LLM[OpenRouter: GLM 5.3 Flash, fallbacks Particle 1 and Ling]
    QA --> AN[(Analytics log)]
    API --> AN
```

## Ingestion (any document size)
```mermaid
flowchart TD
    A[Upload streamed to disk in 1 MB pieces] --> B[Background thread, 2 at a time]
    B --> C[Parse page by page: PDF, DOCX, TXT, MD, CSV, JSON, HTML]
    C --> D[Chunk: about 180 words, 30 word overlap, never across pages, detect headings]
    D --> E[Batch of 200 chunks added to store]
    E --> C
    C --> F[Finalize: BM25 statistics, persist to data/docs]
    F --> G[Status ready: searchable]
    G --> H[Summary, key facts, suggested questions: map-reduce over sampled groups]
```

## Question answering
```mermaid
flowchart TD
    Q[Question] --> CA{Answer cache hit?}
    CA -->|yes| R1[Replay answer in about 1 ms, 0 tokens]
    CA -->|no| QE[Query expansion: 2 extra queries from key terms]
    QE --> S[BM25 search per query, k=16]
    S --> RRF[Reciprocal rank fusion]
    RRF --> GATE{Top relevance above 0.12?}
    GATE -->|no| NF[Add document-wide passages instead of refusing]
    GATE -->|yes| MMR[MMR diversification: pick 7 distinct passages]
    MMR --> NB[Neighbour expansion on top 2 passages]
    NB --> P[Build numbered context under a word budget]
    P --> L[Stream from the model with strict grounding prompt]
    L --> V[Validate citations against retrieved passages]
    V --> D[Done event: answer, citations, metrics]
```

## Streaming protocol (server sent events)
```mermaid
sequenceDiagram
    participant B as Browser
    participant S as Server
    B->>S: POST /api/ask
    S-->>B: status retrieving, ranking, reading
    S-->>B: sources (numbered passages)
    S-->>B: status generating, thinking
    S-->>B: token, token, token
    S-->>B: done (answer, citations, metrics)
```

## Why it scales
- Memory: pages are streamed, never held as a list. A 500 page PDF peaked at about 26 MB of Python memory.
- Speed: inverted index with packed postings. Search over 50,000 chunks takes 5 to 60 ms.
- Cost: the model always sees about 7 passages, so the prompt size is constant for a 5 page or a 5000 page document.
- Trust: citations are validated, and weak retrieval widens the context, and when the document truly lacks a detail the answer says so plainly.

## Metrics tracked per question
Time to first token, total time, retrieval time, model time, prompt tokens, completion tokens, cached tokens, tokens per second, cache hit, model, passages, answered or not found or error.
