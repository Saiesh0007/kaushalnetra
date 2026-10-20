---
title: KaushalNetra
emoji: 🎓
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: AI compliance monitoring for skill training centres (SIH 2026, PS 26245)
---

# KaushalNetra

Privacy-first compliance monitoring for government-funded training centres, built for Smart India Hackathon 2026
(problem statement SIH26245). It turns a centre's existing CCTV into attendance and equipment checks without
identifying anyone: people are pixelated on the edge device, and only counts and aggregate events reach the server.

**In this demo**

- **Overview, Centres, Alerts:** 65 centres. Five ran through the AI pipeline on real stock footage; sixty are
  simulated to show scale and are labelled as such everywhere.
- **Control room:** press *Start live run* to run the real edge AI on a demo centre's recorded footage. Watch the
  pixelated count, the attendance alert, and cut the network to see events queue on the device.
- **Copilot:** ask questions about compliance data in English or Hindi.
- **Accuracy lab:** every number comes from an evaluation run on held-out data.

The database resets whenever the Space restarts. Source: https://github.com/Saiesh0007/kaushalnetra
