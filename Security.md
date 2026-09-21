# Security

## Overview

NaraRouter is a Python agent that controls your local Windows desktop via mouse, keyboard, screen capture, and app launching. This document outlines the security model, threat assumptions, and hardening guidelines.

## Threat Model

### Assets

- Local system access (mouse, keyboard, screen)
- API keys and credentials stored in `.env`
- User session data on the host machine

### Threat Actors

| Actor | Capability | Motivation |
|-------|-----------|------------|
| Attacker with code execution on host | Full control | Compromise the agent process |
| Network attacker | MitM on API calls | Intercept credentials / inject commands |
| Malware | Runs as same user | Abuse agent privileges |
| Curious third party | Physical access | Read `.env` or source code |

## Security Principles

1. **Local-only by default** — NaraRouter runs entirely on the local machine. No telemetry, no phoning home.
2. **Credentials in `.env` only** — Secrets are read from environment variables, never hardcoded.
3. **Least privilege** — The agent runs with the privileges of the user who starts it. Do not elevate.
4. **No network exposure** — The GUI and terminal clients bind to localhost; no inbound ports are opened.

## Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `.env` file exposed via repo or backup | `.env` is gitignored. Do not commit it. |
| Screen capture may include sensitive content | Agent only captures what the user explicitly triggers. |
| Keyboard/mouse injection could be abused | Runs only when invoked by the user or an authorized REPL session. |
| Dependencies may contain vulnerabilities | Pin versions in `requirements.txt`; audit periodically with `pip-audit`. |
| API keys leaked in logs | Avoid logging secret values; filter `os.getenv` outputs. |

## Hardening Checklist

- [ ] Keep `.env` out of version control (already gitignored).
- [ ] Rotate API keys if you suspect leakage.
- [ ] Run in a standard user account — never as Administrator/root.
- [ ] Regularly update dependencies (`pip install -r requirements.txt --upgrade`).
- [ ] Review logs for accidental credential exposure.
- [ ] Use a firewall rule blocking inbound connections to Python processes if desired.

## Reporting a Vulnerability

If you discover a security issue, please open a private GitHub Security Advisory or email the maintainer directly. Do not post vulnerability details in public issues.

---

*Last reviewed: 2026-09-21*
