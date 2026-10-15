# Drishti: AI Compliance Monitoring for Training Centres

> SIH 2026 · Problem Statement **26245** · Ministry of Skill Development and Entrepreneurship (MSDE) · Theme: Smart Education

Drishti turns the CCTV cameras that already exist in government-funded training centres into compliance sensors. A small edge device at each centre analyses the camera feeds on site. It then sends only compact, privacy-safe events to a central dashboard:

- **Attendance discrepancies:** the observed head-count is checked against the attendance the centre submitted.
- **Infrastructure gaps:** sanctioned equipment that is missing, relocated or never used.
- **Camera tampering:** feeds that are looped, frozen, covered or moved.

No face recognition is used anywhere. Raw video never leaves the centre.

## Why it matters

- Physical inspections happen only periodically. Ghost attendance and missing equipment between visits go unnoticed.
- Drishti flags problems as they happen and ranks centres by risk, so inspectors visit the right centres first.

## Repository layout

```
SIH/
├── README.md            ← you are here
├── docs/
│   ├── Plan.md          ← master plan: how we win + startup & funding path
│   ├── Project.md       ← problem statement, scope, deliverables, success criteria
│   ├── Architecture.md  ← system architecture, components, data flow, deployment modes
│   ├── Design.md        ← detailed design: algorithms, data model, APIs, dashboard
│   ├── Phases.md        ← build plan, milestones, task breakdown
│   ├── Rules.md         ← engineering, privacy and contribution rules (mandatory)
│   └── Memory.md        ← decision log, status, open questions, glossary
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

> The commands below show the planned workflow. See [docs/Phases.md](docs/Phases.md) for current status.

```bash
# Backend
cd server && python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000/docs

# Edge agent: run on a sample video in place of an RTSP camera
cd edge && pip install -r requirements.txt
python -m agent --config configs/centre_demo_a.yaml --source ../data/centre_a.mp4

# Dashboard
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

## Documentation

Start with [docs/Project.md](docs/Project.md), then [docs/Architecture.md](docs/Architecture.md). Read [docs/Rules.md](docs/Rules.md) before writing any code.

## Team

| Name | Role |
|---|---|
| Saiesh Sutar | Product, data collection, testing, pitch |
| Claude (AI pair) | Code, ML pipeline, docs |
