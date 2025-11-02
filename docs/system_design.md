# System Design Document — Surveil Summarizer

## 1. Objective

To build a real-time video surveillance summarization system that automatically generates natural language descriptions of live or uploaded video feeds and allows users to ask natural-language questions about recent activities (e.g., “Was anyone carrying a backpack in the last 10 minutes?”).

---

## 2. System Overview

The system processes live or uploaded video to generate time-stamped summaries and supports query-based retrieval via natural language. It consists of the following main modules:

1. **Frontend** — Web-based interface for uploading or streaming video, viewing captions, and asking questions.
2. **Backend (FastAPI)** — Handles video upload, frame extraction, caption generation, QA, and serves results via REST and WebSocket APIs.
3. **Captioning Engine (Multimodal LLM)** — Converts frames into descriptive text.
4. **Database / Storage** — Stores summaries, timestamps, embeddings, and metadata.
5. **Retrieval and QA Engine** — Uses embeddings and cosine similarity to retrieve relevant summaries and generate answers.

---

## 3. Workflow

### 3.1 Video Upload / Ingestion

* User uploads a short MP4 file or streams a live feed.
* Backend extracts sampled frames (e.g., 1 fps).
* Frames are grouped into **overlapping windows** (20s window, 10s stride).
* Each window is sent to a captioning model (mock → GPT-4V → local model).
* Generated summaries are stored with timestamps and embeddings.

### 3.2 Caption Generation

Each 20s window produces a concise textual summary. Example:

```
[0–20s]: Two people enter the north gate, one carrying a box.
[10–30s]: The same individuals walk toward the loading area.
```

Captions are saved in a database with fields:

```
(video_id, start, end, text, embedding, confidence)
```

### 3.3 Query-Based QA

* User asks a question about a video.
* Question embedding is computed.
* Retrieve top-K most similar summaries via cosine similarity.
* Apply a **threshold decision** to filter low-confidence results:

  * Dynamic rule: `threshold = max(global_T, α × max_score)` (e.g., global_T = 0.35, α = 0.6)
* Merge overlapping windows and pass context to the LLM.
* LLM generates final answer and cites supporting timestamps.

### 3.4 Real-Time Streaming (optional)

* Frames from a live feed are streamed via WebSocket.
* Server buffers frames in sliding 2s windows.
* Summaries are produced continuously and broadcast to connected clients.

---

## 4. System Architecture

```
Frontend (HTML/JS)
 ├── Upload video (REST /upload)
 ├── Live view (WebSocket /ws/stream)
 ├── Display captions synced to timestamps
 └── QA interface (REST /qa)

Backend (FastAPI)
 ├── Frame extraction (OpenCV)
 ├── Captioning (GPT-4V / Local Model)
 ├── Embedding generation (OpenAI / HF)
 ├── Database (SQLite + FAISS)
 └── Threshold-based retrieval & LLM QA

Storage
 ├── Video files (data/raw)
 ├── Extracted frames (data/processed)
 ├── Summaries table (SQLite)
 └── Embeddings (FAISS index)
```

---

## 5. Chunking & Overlap Strategy

* **Window size:** 20 seconds
* **Stride:** 10 seconds (50% overlap)
* **Reason:** Ensures events spanning window boundaries appear in at least one full summary.
* **Merging rule:** Merge overlapping/nearby windows (≤ 2s apart) before QA synthesis.

---

## 6. Similarity Thresholding Strategy

* **Retrieval:** Top-K (e.g., 8) windows per query.
* **Cosine similarity threshold:** Determined via validation data.
* **Dynamic rule:**

  ```
  threshold = max(global_T, α × max_score)
  ```

  where `global_T = 0.35`, `α = 0.6` (tuned later).
* **Fallback behavior:**

  * If no candidate ≥ threshold → “No evidence found.”
  * If candidates below confidence → mark as *low confidence*.

---

## 7. Model Choices

* **Frame Extraction:** OpenCV (1 fps sampling)
* **Caption Model:** Mock → GPT-4V → LLaVA/Qwen-VL (future local)
* **Embedding Model:** OpenAI text-embedding-3-small (or HF alternative)
* **QA Model:** GPT-4-turbo (text-only) or local text LLM

---

## 8. Deployment Infrastructure

* **Containerization:** Dockerfile for reproducible build
* **Testing:** Pytest with FastAPI TestClient
* **CI/CD:** GitHub Actions (run tests on push)
* **Environment:** Python 3.11, FastAPI, SQLite, FAISS
* **Frontend hosting:** Served via FastAPI static or separate React app

---

## 9. Evaluation Metrics

* **Captioning quality:** BLEU, METEOR, CIDEr (vs ground-truth captions)
* **Retrieval QA performance:** Precision, Recall, F1, AUC on validation QA pairs
* **Latency:** Time from frame → caption, caption → answer
* **User feedback:** Qualitative correctness & satisfaction

---

## 10. Future Enhancements

1. Integrate motion-based segmentation for adaptive windowing.
2. Add background job queue (Celery + Redis) for long video processing.
3. Add role-based access control & secure video uploads.
4. Support streaming RTSP feeds for real CCTV integration.
5. Add interactive timeline visualization with QA evidence overlay.

---

## 11. Summary

This design enables a production-grade multimodal video summarization and QA system using FastAPI, Docker, and multimodal LLMs. It balances real-time responsiveness with retrieval accuracy using overlapping window chunking, dynamic thresholding, and evidence-grounded question answering. The system is modular, extensible, and suitable for both local demos and scalable deployments.
