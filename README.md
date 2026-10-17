# KaushalNetra: AI Compliance Monitoring for Training Centres

> SIH 2026 · Problem Statement **26245** · Ministry of Skill Development and Entrepreneurship (MSDE) · Theme: Smart Education

KaushalNetra turns the CCTV cameras that already exist in government-funded training centres into compliance sensors. A small edge device at each centre analyses the camera feeds on site. It then sends only compact, privacy-safe events to a central dashboard:

- **Attendance discrepancies:** the observed head-count is checked against the attendance the centre submitted.
- **Infrastructure gaps:** sanctioned equipment that is missing, relocated or never used.
- **Camera tampering:** feeds that are looped, frozen, covered or moved.

No face recognition is used anywhere. Raw video never leaves the centre.

## Why it matters

- Physical inspections happen only periodically. Ghost attendance and missing equipment between visits go unnoticed.
- KaushalNetra flags problems as they happen and ranks centres by risk, so inspectors visit the right centres first.

## Repository layout

```
SIH/
├── README.md            ← you are here
├── edge/                ← edge agent (Python): capture, inference, event queue
├── server/              ← FastAPI backend: ingest, rules engine, REST API
├── dashboard/           ← React + Vite monitoring dashboard
├── ml/                  ← training, evaluation, accuracy assessment
├── data/                ← sample / simulated footage (git-ignored)
└── scripts/             ← dev utilities, demo seeding, degradation simulator
```

## Tech stack

| Layer | Choice |
|---|---|
| Detection | Ultralytics YOLO (head/person), YOLO-World (open-vocabulary equipment) |
| Tracking | ByteTrack (session-scoped IDs only) |
| Item verification | DINOv2-small embeddings + per-item calibrated thresholds |
| Video / CV | OpenCV (RTSP capture, ORB alignment, MOG2 motion, CLAHE) |
| Edge runtime | ONNX Runtime / OpenVINO (int8), Python 3.11 |
| Backend | FastAPI, SQLAlchemy, SQLite (demo) → PostgreSQL (production) |
| Dashboard | React, Vite, TypeScript, Recharts, Leaflet |

## Quick start

```bash
# one-time setup (Python 3.12 + Node 20+)
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe torch torchvision --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/Scripts/python.exe -r edge/requirements.txt -r server/requirements.txt
cd dashboard && npm install && npm run build && cd ..

# run the whole demo: API + dashboard on http://127.0.0.1:8000 (seeds the demo database on first run)
.venv/Scripts/python scripts/demo.py

# in a second terminal: play a centre's footage live through the edge AI (blurred preview + live alert)
.venv/Scripts/python scripts/demo.py live b
```

| What | Command |
|---|---|
| Re-seed the demo from scratch | delete `server/var`, then `python scripts/seed_demo.py` |
| Equipment / tamper / count / bandwidth evaluations | `python ml/eval/infra_eval.py`, `tamper_eval.py`, `count_eval.py --head <weights>`, `bandwidth_eval.py` |
| Regenerate the simulated equipment scenario | `python scripts/make_centre_c.py` |
| Dashboard dev server (hot reload) | `cd dashboard && npm run dev` → http://127.0.0.1:5173 |
| AI copilot with an LLM (optional, free tiers) | set `KNETRA_LLM_BASE_URL`, `KNETRA_LLM_API_KEY`, `KNETRA_LLM_MODEL` (any OpenAI-compatible endpoint); without them the copilot answers offline |

## Data sources (all free)

| Data | Use | Licence |
|---|---|---|
| SCUT-HEAD PartA (2,000 classroom CCTV frames, 67k labelled heads) | train + evaluate the head detector | free for academic research |
| Mixkit stock clips (classroom, labs) | AI-pipeline demo centres A, B, D | Mixkit Stock Video Free License |
| Unsplash room photos | equipment scenarios (`ml/sim`) with exact ground truth | Unsplash License |
| OpenCV `vtest.avi` | smoke + tamper tests | OpenCV sample data |
| DataMeet India boundaries | dashboard map (official composite boundary) | CC BY 4.0 |

## Documentation

Design notes, the privacy note and the pitch material are kept outside this repository.

## Team

| Name | Role |
|---|---|
| Saiesh Sutar | Product, data collection, testing, pitch |
| Claude (AI pair) | Code, ML pipeline, docs |
