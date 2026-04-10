# 竹本研ゼミAIアシスタント — システム概要

```mermaid
flowchart TD
    subgraph FRONT["🎓 教室前方（発表エリア）"]
        direction LR
        PRESENTER["🧑‍🏫 発表者"]
        MIC["🎙️ AT2020USB-X\nUSBマイク"]
        LAPTOP["💻 研究室ノートPC"]
        PRESENTER -- 発話 --> MIC
        MIC -- USB接続 --> LAPTOP
    end

    subgraph SERVER["⚡ 研究室GPUサーバー"]
        direction LR
        STT["🗣️ 音声\nテキスト変換"]
        TRANS["🌐 日本語→英語\n自動翻訳"]
        LLM["🤖 LLM\nサーバー"]
    end

    subgraph ROOM["👥 教室（約25名の学生）"]
        direction LR
        PROJECTOR["📽️ プロジェクター\nリアルタイム字幕"]
        DEVICES["📱 学生の端末\n字幕表示・チャットボット"]
    end

    LAPTOP -- 音声データをSSH送信 --> SERVER
    SERVER -- リアルタイムテキスト --> PROJECTOR
    SERVER -- Webインターフェース --> DEVICES

    classDef input fill:#4a7fcb,color:#fff,stroke:#2d5a9e
    classDef server fill:#2d8a4e,color:#fff,stroke:#1a5c32
    classDef output fill:#d4813a,color:#fff,stroke:#a05c1f

    class PRESENTER,MIC,LAPTOP input
    class STT,TRANS,LLM server
    class PROJECTOR,DEVICES output
```

### 教室での流れ

前方に設置したAT2020USB-Xマイクが発表音声を収音し、研究室ノートPCがその音声をSSH経由でGPUサーバーへ送信します。サーバー側では、音声テキスト変換・日本語英語翻訳・LLMチャットボットの3処理が並行して動きます。

結果は2つの経路で同時に届きます。リアルタイムの字幕はプロジェクターに映し出されます。また、教室内の学生25名はそれぞれのスマホやPCでWebページを開き、同じ字幕を確認しながら、チャット欄から過去の研究資料をもとにAIへ質問できます。

外部サービスへのデータ送信は一切ありません。処理はすべて大学ネットワーク内で完結し、追加費用もゼロです。
