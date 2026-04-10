# Email: Seminar Assistant System — Proposal to Prof. Takemoto & Prof. Okamoto

---

**To:** 竹本拓治 先生 / Prof. Takuji Takemoto
**CC:** 岡本 先生 / Prof. Okamoto
**From:** Amil Khanzada (kad23802)
**Subject:** 【ご提案】竹本研ゼミ向けリアルタイムAIアシスタントの開発について

---

## Japanese (Original)

竹本先生、岡本先生

お世話になっております。地方創生本部の Amil Khanzada です。

この度、竹本研究室のゼミ活動をサポートする目的で、**リアルタイム音声文字起こし・翻訳・Q&Aシステム**のプロトタイプを自主的に開発しましたので、ご報告とご提案を申し上げます。

---

### 背景と目的

本学では現在、国際化推進の一環として、海外からの大学院生の受け入れを積極的に進めております。今後、英語話者の留学生が竹本研に参加した際、日本語中心のゼミ環境への適応が大きな課題となることが予想されます。

この問題を技術的に解決するため、以下の機能を持つシステムを構築いたしました。

---

### システム概要

本システムは、ゼミ室のマイクで収音した音声をリアルタイムで処理し、**学生向けのWebブラウザ画面**に以下を表示します：

1. **リアルタイム文字起こし**（日本語・英語・自動判別）
   ゼミ中の発言を即座にテキスト化します。

2. **リアルタイム翻訳**（日本語 → 英語）
   文字起こしされた日本語を英語に自動翻訳し、各発言の下に表示します。

3. **ラボ知識ベースQ&A（RAG）**
   学生が画面のチャット欄に質問を入力すると、研究室の過去資料（ゼミノート、連絡事項など）を参照して回答します。現時点ではLINEグループの過去ログを学習済みです。今後、ゼミ発表資料や研究ノートを追加することで精度が向上します。

---

### 技術的特徴

- **学外データ送信なし**：すべてのAI処理は大学ネットワーク内のGPUサーバー（takelab）上で完結します。外部クラウドAPIは一切使用しません。
- **ゼロコスト**：既存のサーバーリソースを活用するため、追加の費用は発生しません。
- **すぐに利用可能**：プロトタイプは動作中です。次回のゼミでライブデモをお見せできます。

---

### ご依頼

つきましては、次回のゼミにて**5〜10分程度のライブデモ**をさせていただく機会をいただけますでしょうか。実際に音声を入力し、文字起こし・翻訳・Q&Aの動作をご確認いただけます。

ご多忙の中恐れ入りますが、ご検討のほどよろしくお願い申し上げます。

Amil Khanzada
地方創生本部 / 特任助教
福井大学
kad23802 / amil.k@u-fukui.ac.jp

---

## English Translation

Dear Prof. Takemoto, Prof. Okamoto,

I hope this message finds you well. This is Amil Khanzada from the Regional Revitalization Headquarters.

I am writing to report that I have independently developed a prototype **real-time speech transcription, translation, and Q&A system** designed to support the Takemoto Lab seminar activities.

---

### Background and Purpose

Our university is actively working to attract international graduate students as part of its internationalization initiatives. When English-speaking students join the Takemoto Lab, adapting to a Japanese-language seminar environment is expected to be a significant challenge.

To address this with technology, I have built a system with the following capabilities.

---

### System Overview

This system processes audio captured from a seminar room microphone in real time and displays the following on a **student-facing web interface**:

1. **Real-time transcription** (Japanese, English, or auto-detect)
   Spoken words during the seminar are instantly converted to text.

2. **Real-time translation** (Japanese → English)
   Transcribed Japanese is automatically translated into English and displayed beneath each utterance.

3. **Lab Knowledge Base Q&A (RAG)**
   Students can type questions into a chat panel. The system searches past lab materials (seminar notes, announcements, etc.) and generates an answer. The LINE group chat history is already loaded. Accuracy improves as more materials (seminar slides, research notes) are added.

---

### Technical Highlights

- **No data leaves the university network**: All AI processing runs on the in-house GPU server (takelab). No external cloud APIs are used.
- **Zero cost**: The system uses existing server resources — no additional budget is required.
- **Ready now**: The prototype is operational. I can demonstrate it live at the next seminar.

---

### Request

I would like to respectfully request **5–10 minutes at the next seminar for a live demonstration**, where I can show transcription, translation, and Q&A working in real time with actual audio input.

Thank you very much for your time and consideration.

Amil Khanzada
Specially Appointed Assistant Professor
Regional Revitalization Headquarters, University of Fukui
kad23802 / amil.k@u-fukui.ac.jp
