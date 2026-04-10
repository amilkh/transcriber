# Takemoto Lab Seminar Assistant — System Architecture

```mermaid
flowchart TD
    MIC["🎤 USB Microphone"]
    BROWSER["Browser\n(Student UI)"]
    LOCAL["Local FastAPI\n:8080"]
    TUNNEL["SSH Tunnel\n19001 · 11435→11434"]
    STT["Vosk STT\ntakelab:19001\nJA / EN models"]
    LLM["Ollama LLM\ntakelab:11434\nqwen2.5:14b · RTX 5090"]
    KB["Knowledge Base\ncontext/ files\n(LINE chat, notes, slides)"]

    MIC -->|"Web Audio API\n16kHz PCM"| BROWSER
    BROWSER -->|"PCM chunks\nWebSocket"| LOCAL
    LOCAL -->|"transcript\n+ status"| BROWSER
    LOCAL <-->|"WebSocket\nbridge"| TUNNEL
    TUNNEL <-->|"audio stream"| STT
    STT -->|"partial / final\ntranscript"| TUNNEL

    BROWSER -->|"POST /api/translate\nJapanese text"| LOCAL
    BROWSER -->|"POST /api/ask\nquestion"| LOCAL
    LOCAL -->|"generate prompt"| LLM
    LLM -->|"EN translation\nor RAG answer"| LOCAL
    KB -->|"top-k chunks\nkeyword search"| LOCAL

    subgraph takelab ["takelab — Remote GPU Server"]
        STT
        LLM
        KB
    end
```

## Component Summary

| Component | Where | Technology | Purpose |
|---|---|---|---|
| Browser UI | Local | HTML/JS, Web Audio API | Mic capture, transcript + translation display, Q&A chat |
| Local App | Local | Python FastAPI | WebSocket bridge, `/api/translate`, `/api/ask` |
| RAG Indexer | Local | Python (startup) | Indexes `context/` files into searchable chunks |
| STT Service | takelab | Vosk (Python) | Real-time speech-to-text, JA + EN models |
| LLM Service | takelab | Ollama + qwen2.5:14b | JA→EN translation and RAG Q&A |
| GPU | takelab | NVIDIA RTX 5090 (32 GB) | Fast local inference — no cloud API needed |
| Transport | SSH tunnel | SSH port forward | Secure, zero-config networking |

## Key Design Decisions

- **No cloud APIs** — all AI runs on the existing takelab GPU, zero ongoing cost, no data leaves the university network.
- **Language switching** — Vosk restarts with the correct JA/EN model on selector change; auto-mode detects language from the audio stream.
- **RAG corpus** — drop files into `context/` and restart the app to re-index. No vector DB required for prototype; can upgrade to embeddings later.
- **Latency** — STT partials appear within ~600 ms. Translation adds ~1–2 s per sentence (GPU inference).
