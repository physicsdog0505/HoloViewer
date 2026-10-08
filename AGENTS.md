# Public HoloViewer agent entrypoint

**MANDATORY FIRST READ:** [HOLOVIEWER_PROJECT_GUIDELINES.md](HOLOVIEWER_PROJECT_GUIDELINES.md) from the current GitHub revision before any work. Follow its preflight, 8501 functional baseline, 4174 UI baseline, active freeze and mandatory prompt prefix. If it cannot be read, STOP risky work.

**MANDATORY CROSS-WINDOW STATE:** Read [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) before resuming work, and use [docs/HANDOFF_TEMPLATE.md](docs/HANDOFF_TEMPLATE.md) for each cross-window transfer. Verify all stated SHA, PR and deployed status from current sources; treat contradictions as blockers for risky work.

This is a separate **public** repository. Never copy private Collector SQLite, credentials, PTT auth, YouTube/API tokens, local environment files or unreviewed private assets. Public release, UI changes, integration, GitHub Pages deployment and merge require separately verified evidence and user approval. The old Streamlit Community Cloud app has been removed; do not redeploy it. Read the public README and relevant Issue/PR/current code before acting. A green CI run does not mean the deployed site or 8501/4174 parity is accepted.
