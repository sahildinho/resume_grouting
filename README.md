# Resume Copilot

**Resume Copilot** is an AI-powered resume tailoring, verification, and interview-prep studio. You provide your existing resume, a target job description (JD), and a LaTeX (`.tex`) template, and Resume Copilot tailors your bullet points, checks every claim against your real experience, runs ATS hygiene checks, compiles a clean `.tex` / PDF resume, and builds a personalized study roadmap for any skill gaps.

---

## Features

- **Flexible Inputs**: Upload a resume (`.pdf`, `.docx`, `.yaml`, `.txt`, or pasted text), a job description (file, pasted text, or URL), and your own LaTeX `.tex` template (or use the built-in sample template and presets).
- **Two Tailoring Modes**:
  - **Grounded Mode** *(default)*: Strictly rewrites and aligns bullets using only facts from your real experience.
  - **Hypothetical Mode**: Generates aspirational bullets for missing skills while flagging unverified claims for your review.
- **Claim Verification & Human-in-the-Loop (HITL) Review**: Highlights unsupported or partially supported claims so you can approve, edit, or reject them before finalizing.
- **ATS Hygiene Checks**: Flags formatting, keyword, and section issues that can hurt applicant tracking system parsing.
- **LaTeX & PDF Export**: Populates your `.tex` template safely and compiles to PDF automatically when `tectonic` or `pdflatex` is installed (or lets you download `.tex` for Overleaf).
- **Skill-Gap Study Roadmap**: Tracks missing skills in a **To-Learn Queue** and generates a structured **Study Plan** (`StudyPlan.md` / `StudyPlan.json`) where you can mark topics as studied.
- **Bring Your Own Key (BYOK)**: Supports **Google Gemini**, **Anthropic Claude**, or local **Ollama** models.

---

## Prerequisites

- **Python 3.11+**
- At least one LLM provider:
  - A **Gemini API key** (default), **Anthropic API key**, or a local **Ollama** instance (`http://localhost:11434`).
- *(Optional)* **Tectonic** or **TeX Live (`pdflatex`)** on your `PATH` if you want one-click local PDF compilation. Without it, you can still download the generated `.tex` file and compile it in Overleaf.

---

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/<your-username>/resume-copilot.git
   cd resume-copilot
   ```

2. **Create and activate a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   ```
   *(Optional, for running tests)*:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Configure your API key**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and add your key (e.g. `GEMINI_API_KEY=...` or `ANTHROPIC_API_KEY=...`).
   > You can also enter or override your API key directly in the Web UI **Settings** panel without saving it to disk.

---

## Running the App

### Option 1: Lightweight Web Studio (Recommended)
```bash
python app.py
```
This starts the local server (default `http://127.0.0.1:8000`) and opens the Web UI in your browser.
Useful flags:
- `--port 8080` to choose a custom port
- `--no-browser` to start without auto-opening a browser tab

### Option 2: Streamlit Bridge
```bash
streamlit run app.py
```

### Option 3: Uvicorn Directly
```bash
uvicorn api.app:app --reload --port 8000
```

---

## User Guide

1. **Configure Provider & Key**: Click **Settings** in the top bar to pick your provider (`gemini`, `claude`, or `ollama`), model name, and optional session API key (if not already set in `.env`).
2. **Start a New Tailoring Session**:
   - **Quick Try**: Select a built-in sample preset (e.g., Software or Mechanical) to test the workflow immediately.
   - **Custom Run**: Upload your resume (`.pdf`, `.docx`, `.yaml`, or `.txt`), paste or upload the target Job Description (or paste a job posting URL), and upload your `.tex` resume template (or check the default sample template option).
   - Choose **Grounded** (strictly factual) or **Hypothetical** mode.
3. **Run & Inspect Progress**: Click **Start Tailoring** to watch live progress across profiling, tailoring, NLI verification, and ATS checks.
4. **Review Flagged Claims (HITL)**: If any tailored bullet needs confirmation, review the evidence in the **Review** panel and approve, edit, or reject it.
5. **Download Your Resume**: Export the tailored `.tex` file or compiled `.pdf` directly from the session panel.
6. **Follow Your Study Plan**: Open the **Study Plan** / **To-Learn Queue** tabs to review missing JD skills and check off topics as you study them.

---

## Running Tests

```bash
pytest -q
```

---

## Privacy & Security Note

- `.env` and `runs/` are git-ignored by default so your API keys, uploaded resumes, and generated outputs stay local to your machine.
- Never commit `.env` or personal credentials to version control.
