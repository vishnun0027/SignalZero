# SignalZero

*Weak Signal Intelligence for Emerging Technologies*

## The Vision

SignalZero is built on a single, powerful premise: **to detect emerging technologies 3–6 months before they enter mainstream discourse.** 

We are building a "scientific telescope" pointed at the frontier of human knowledge, designed to detect faint light from ideas that have not yet arrived. SignalZero monitors what has *not yet trended* — sparse, early-stage signals that historically precede major breakthroughs.

## The Objective

Every organization that builds on emerging technology faces the same problem: by the time a breakthrough is visible on mainstream channels (news, tech blogs, social media), it is already 12–18 months old. The decision window — when early adopters gain a structural advantage — has already closed.

Current tools like search trends or news aggregators only measure what is already known. SignalZero aims to close this intelligence gap. By automatically monitoring scientific literature and technical communities, it algorithmically extracts early indicators of paradigm shifts and generates structured executive briefings. 

## How It Works: The "Weak Signal" Phenomenon

A weak signal is an early, faint, and ambiguous indicator of a future development. SignalZero looks for three specific patterns that historically precede major technological breakthroughs:

1. **Cross-Field Anomaly:** When an idea originates in one specific field but is quickly adopted by researchers in entirely different domains. This indicates a general-purpose mechanism solving broad problems.
2. **Vocabulary Emergence:** When a completely new technical term appears with near-zero frequency, then accelerates in usage over a short period.
3. **Convergent Discovery:** When multiple independent research groups publish work on the exact same novel concept simultaneously, indicating the idea has reached its natural threshold of discovery.

## Why This Matters

SignalZero is not a productivity tool or a chat interface. It is a scientific instrument designed to find the next big thing while it is still just a handful of papers and a new idea. The most important outcome is gaining a deep understanding of how scientific knowledge propagates, how ideas cross boundaries, and how breakthroughs look in their earliest, most fragile moments — before the world even has words for them.

---

## 🚀 Production Deployment

This project is deployed automatically to the production VM using GitHub Actions when changes are pushed to `main`.

### Automated CI/CD
The deployment workflow is configured in [.github/workflows/ci-cd.yml](file://.github/workflows/ci-cd.yml) (renamed from `ci.yml` to standardise project structures) and runs on pushes to `main`. It connects to the VM via SSH, checks out the code, and triggers the deployment script.

### Unified Deployment Script
All deployment steps are encapsulated in [scripts/deploy.sh](file://scripts/deploy.sh):
- **Secrets Management**: If the script is run in CI, it writes the `.env` configuration file dynamically from the `DOTENV_CONTENT` environment variable.
- **Dependencies**: Runs `uv sync --frozen` to prepare the isolated virtual environment.
- **Systemd User Configuration**: Templates the systemd service and timer files dynamically (resolving absolute directories and removing explicit User/Group controls for systemd --user manager mode) and copies them to `~/.config/systemd/user/`.
- **Linger Activation**: Keeps user services alive after the SSH session disconnects.
- **Service Management**: Restarts `signalzero_api.service`, `signalzero.timer`, and `signalzero_digest.timer`.
- **Health Check**: Runs a health loop against `http://localhost:8007/api/health` to verify success.

To trigger a manual deploy on the VM, execute:
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

