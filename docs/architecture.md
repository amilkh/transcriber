# Takemoto Lab Seminar Assistant — System Architecture

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  SEMINAR ROOM (Local Machine — Amil's PC)                           │
│                                                                     │
│   🎤 USB Microphone                                                  │
│        │                                                            │
│        ▼  Web Audio API (AudioWorklet)                              │
│   Browser  ──── 16kHz PCM chunks (WebSocket) ────► Local FastAPI   │
│   (Chrome)  ◄─── live transcript + translation ──── app (:8080)    │
│        │                                              │             │
│        │  Student UI                                  │ WebSocket   │
│        │  ┌─────────────────────┐                     │ bridge      │
│        │  │  [Live Transcript]  │                     │             │
│        │  │  Japanese text      │                     │             │
│        │  │  ↳ English (LLM)    │                     │             │
│        │  ├─────────────────────┤                     │             │
│        │  │  [Lab Assistant]    │                     │             │
│        │  │  Q: "What is...?"   │ ◄── /api/ask ───────┤             │
│        │  │  A: (RAG answer)    │                     │             │
│        │  └─────────────────────┘                     │             │
│                                                       │             │
└───────────────────────────────────────────────────────┼─────────────┘
                                                        │
                              SSH Tunnel (port forward) │
                              19001: transcriber        │
                              11435→11434: LLM          │
                                                        │
┌───────────────────────────────────────────────────────┼─────────────┐
│  TAKELAB SERVER (Remote GPU Machine)                  │             │
│                                                       ▼             │
│  ┌─────────────────────────┐        ┌────────────────────────────┐  │
│  │  Vosk STT Service       │        │  Ollama LLM Service        │  │
│  │  (:19001)               │        │  (:11434)                  │  │
│  │                         │        │                            │  │
│  │  Language: JA / EN / auto        │  Model: qwen2.5:14b        │  │
│  │  Models:                │        │  GPU: RTX 5090 (32GB)      │  │
│  │  • vosk-small-ja-0.22   │        │                            │  │
│  │  • vosk-small-en-0.15   │        │  Tasks:                    │  │
│  │                         │        │  • JA→EN translation       │  │
│  │  Output:                │        │  • RAG question answering  │  │
│  │  • partial hypotheses   │        │                            │  │
│  │  • final transcripts    │        └────────────────────────────┘  │
│  └─────────────────────────┘                                        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Knowledge Base (RAG Corpus)                                │    │
│  │  • Lab LINE group chat history                              │    │
│  │  • [future] Seminar slides and notes                        │    │
│  │  • [future] Research summaries (Amil, Aoyama, etc.)         │    │
│  │  Retrieval: keyword search → top-k chunks → LLM prompt      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Summary

| Component | Where | Technology | Purpose |
|---|---|---|---|
| Browser UI | Local | HTML/JS, Web Audio API | Mic capture, transcript display, Q&A chat |
| Local App | Local | Python FastAPI | WebSocket bridge, translate/ask API endpoints |
| RAG Indexer | Local | Python (startup) | Indexes context/ files into searchable chunks |
| STT Service | takelab | Vosk (Python) | Real-time speech-to-text, JA + EN models |
| LLM Service | takelab | Ollama + qwen2.5:14b | Translation and RAG Q&A |
| GPU | takelab | NVIDIA RTX 5090 | Fast local inference — no cloud API needed |
| Transport | SSH tunnel | SSH port forward | Secure, zero-config networking |

## Key Design Decisions

- **No cloud APIs**: All AI runs on the existing takelab GPU — zero ongoing cost, no data leaves the university network.
- **Language switching**: Vosk restarts with the correct JA/EN model on selector change; auto-mode detects language from the audio stream.
- **RAG corpus**: Plain text files dropped into `context/` are indexed at startup. No vector database required for prototype — can be upgraded to embeddings later.
- **Latency**: STT partial results appear within ~600ms. Translation adds ~1–2s after each sentence (LLM inference on GPU).
