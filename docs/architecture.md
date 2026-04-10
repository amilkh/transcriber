# Takemoto Lab Seminar Assistant — System Overview

```mermaid
flowchart LR
    MIC["🎤 Microphone"]
    LAPTOP["Amil's Laptop"]
    TAKELAB["Takelab GPU Server\n───────────────\n• Speech → Text\n• JA → EN Translation\n• Q&A (Lab Knowledge Base)"]
    STUDENTS["Student Browsers\n───────────────\n• Live transcript\n• English translation\n• Chat Q&A"]

    MIC -->|captures audio| LAPTOP
    LAPTOP -->|audio stream| TAKELAB
    TAKELAB -->|transcript · translation · answers| STUDENTS
```

| | |
|---|---|
| **Input** | USB mic on Amil's laptop captures seminar audio |
| **Processing** | Takelab GPU server — speech recognition, translation, Q&A — all within university network |
| **Output** | Students open a web page on any device to see live transcript, English translation, and ask questions |
| **Cost** | Zero — runs on existing hardware, no external APIs |
