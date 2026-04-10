# Takemoto Lab Seminar Assistant — System Overview

```mermaid
flowchart TD
    subgraph FRONT["🎓 Front of Classroom"]
        direction LR
        PRESENTER["🧑‍🏫 Presenter"]
        MIC["🎙️ AT2020USB-X\nUSB Microphone"]
        LAPTOP["💻 Lab Laptop"]
        PRESENTER -- speaks into --> MIC
        MIC -- USB --> LAPTOP
    end

    subgraph SERVER["⚡ Lab GPU Server"]
        direction LR
        STT["🗣️ Speech\nRecognition"]
        TRANS["🌐 JA → EN\nTranslation"]
        LLM["🤖 LLM\nServer"]
    end

    subgraph ROOM["👥 Classroom — 25 Students"]
        direction LR
        PROJECTOR["📽️ Projector\nLive Transcript"]
        DEVICES["📱 Student Devices\nLive Transcript · Chatbot"]
    end

    LAPTOP -- audio stream over SSH --> SERVER
    SERVER -- real-time text --> PROJECTOR
    SERVER -- web interface --> DEVICES

    classDef input fill:#4a7fcb,color:#fff,stroke:#2d5a9e
    classDef server fill:#2d8a4e,color:#fff,stroke:#1a5c32
    classDef output fill:#d4813a,color:#fff,stroke:#a05c1f

    class PRESENTER,MIC,LAPTOP input
    class STT,TRANS,LLM server
    class PROJECTOR,DEVICES output
```

### How it works in the classroom

The AT2020USB-X microphone sits at the front of the room and captures audio as students present. The Lab Laptop streams that audio over a secure SSH connection to the Lab GPU Server, which runs three components in parallel: speech recognition, a Japanese-to-English translation model, and an LLM server (Ollama with qwen2.5:14b) for the chatbot.

Results flow back out two ways at once. The live transcript appears on the classroom projector so everyone can follow along. The 25 students in the room also have access to a web page on their own phone or laptop showing the same feed, plus a chatbot panel where they can ask questions answered from past lab materials.

Nothing is sent to any external service. All processing stays within the university network, and there is no ongoing cost.
