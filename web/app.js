/* Resume Copilot — Lightweight Vanilla JS Client */

(() => {
  const state = {
    session: null,
    config: null,
    samples: [],
    activeStep: "setup",
    setupMode: "grounded",
    runMode: "grounded",
    resumeSource: "upload",
    texSource: "sample",
    jdSource: "paste",
    kwFilter: "all",
    auditFilter: "ALL",
    auditSearch: "",
    studyFilter: "all",
    hitlTab: "APPROVE",
    queuedRejectClaims: new Set(),
    queuedSurfaceGaps: new Set(),
    settings: {
      provider: localStorage.getItem("rc_provider") || "gemini",
      model: localStorage.getItem("rc_model") || "gemini-3.8-flash",
      apiKey: sessionStorage.getItem("rc_api_key") || "",
      maxIterations: Number(localStorage.getItem("rc_max_iter") || "5"),
    },
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function esc(val) {
    if (val === null || val === undefined) return "";
    return String(val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toast(msg, kind = "info") {
    const stack = $("#toast-stack");
    const el = document.createElement("div");
    el.className = `toast ${kind === "error" ? "toast-error" : kind === "success" ? "toast-success" : ""}`;
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function apiHeaders(extra = {}) {
    const h = { ...extra };
    if (state.settings.apiKey.trim()) {
      h["X-API-Key"] = state.settings.apiKey.trim();
    }
    return h;
  }

  async function apiFetch(url, options = {}) {
    const res = await fetch(url, {
      ...options,
      headers: apiHeaders(options.headers || {}),
    });
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        detail = body.detail || body.message || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  /* ==================== THEME & SETTINGS ==================== */
  function initTheme() {
    const saved = localStorage.getItem("rc_theme") || "light";
    document.documentElement.setAttribute("data-theme", saved);
    $("#btn-toggle-theme").textContent = saved === "dark" ? "☀" : "☾";
  }

  function toggleTheme() {
    const curr = document.documentElement.getAttribute("data-theme");
    const next = curr === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("rc_theme", next);
    $("#btn-toggle-theme").textContent = next === "dark" ? "☀" : "☾";
  }

  function updateSettingsUI() {
    $("#cfg-provider").value = state.settings.provider;
    $("#cfg-model").value = state.settings.model;
    $("#cfg-api-key").value = state.settings.apiKey;
    $("#cfg-max-iter").value = String(state.settings.maxIterations);
    $("#header-model-label").textContent = state.settings.model;

    const cfg = state.config;
    const dot = $("#key-status-dot");
    const box = $("#env-key-status-box");
    const hasEnv =
      cfg &&
      ((state.settings.provider === "gemini" && cfg.has_gemini_key) ||
        (state.settings.provider === "claude" && cfg.has_claude_key) ||
        state.settings.provider === "ollama");
    const hasCustom = Boolean(state.settings.apiKey.trim());

    dot.classList.toggle("ok", Boolean(hasEnv || hasCustom));
    if (box && cfg) {
      box.innerHTML = `
        <strong>Server .env detection:</strong>
        Gemini key: <code>${cfg.has_gemini_key ? "Detected" : "Missing"}</code> ·
        Claude key: <code>${cfg.has_claude_key ? "Detected" : "Missing"}</code> ·
        PDF compiler: <code>${esc(cfg.pdf_compiler || "Not installed (Browser Print/PDF ready)")}</code>
      `;
    }
  }

  /* ==================== STEPPER & NAVIGATION ==================== */
  function setStep(step) {
    state.activeStep = step;
    $$(".step-view").forEach((v) => v.classList.remove("active"));
    $(`#view-${step}`).classList.add("active");
    $$(".step-pill").forEach((b) => b.classList.toggle("active", b.dataset.step === step));
  }

  function syncStepperLocks() {
    const s = state.session;
    const hasSession = Boolean(s);
    const hasTailored = Boolean(s && s.tailored_resume);
    const hasCritic = Boolean(s && s.critic_report);

    $("#step-btn-tailor").disabled = !hasSession;
    $("#step-btn-audit").disabled = !hasCritic;
    $("#step-btn-study").disabled = !hasSession;

    $("#step-btn-setup").classList.toggle("done", hasSession);
    $("#step-btn-tailor").classList.toggle("done", hasTailored);
    $("#step-btn-audit").classList.toggle("done", Boolean(s && s.approved));
    $("#step-btn-study").classList.toggle(
      "done",
      Boolean(s && s.study_plan && s.study_plan.study_items.every((x) => x.studied))
    );
  }

  function updateHeaderFromSession() {
    const s = state.session;
    const mode = s ? s.tailoring_mode || "grounded" : state.setupMode;
    const badge = $("#header-mode-badge");
    badge.className = `mode-badge ${mode === "hypothetical" ? "mode-hypothetical" : "mode-grounded"}`;
    badge.textContent = mode === "hypothetical" ? "✦ Hypothetical Boost" : "Grounded Mode";

    if (!s) {
      $("#header-session-label").textContent = "No active session";
      return;
    }
    const cand = s.base_experience?.candidate_name || "Candidate";
    const role = s.parsed_jd?.role_title || "Role";
    $("#header-session-label").textContent = `${cand} · ${role} (${s.session_id})`;
  }

  /* ==================== STEP 1: SETUP & SAMPLES ==================== */
  function renderSamples() {
    const bar = $("#sample-presets-bar");
    const selRes = $("#select-resume-sample");
    const selJd = $("#select-jd-sample");

    bar.innerHTML = '<span class="preset-label">Quick Demo:</span>';
    selRes.innerHTML = "";
    selJd.innerHTML = "";

    state.samples.forEach((sample) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-ghost btn-sm";
      btn.textContent = sample.label;
      btn.addEventListener("click", () => applySamplePreset(sample.id));
      bar.appendChild(btn);

      const optR = new Option(`${sample.label} (${sample.resume_filename})`, sample.id);
      const optJ = new Option(sample.label, sample.id);
      selRes.add(optR);
      selJd.add(optJ);
    });

    if (state.samples.length > 0) {
      $("#preview-jd-sample").value = state.samples[0].jd_preview;
    }
  }

  function applySamplePreset(sampleId) {
    const sample = state.samples.find((s) => s.id === sampleId);
    if (!sample) return;

    setSegment("resume", "sample");
    setSegment("tex", "sample");
    setSegment("jd", "sample");
    $("#select-resume-sample").value = sample.id;
    $("#select-jd-sample").value = sample.id;
    $("#preview-jd-sample").value = sample.jd_preview;
    toast(`Loaded preset: ${sample.label}. Choose Grounded or Hypothetical mode and click Initialize.`);
  }

  function setSegment(group, val) {
    if (group === "resume") state.resumeSource = val;
    if (group === "tex") state.texSource = val;
    if (group === "jd") state.jdSource = val;

    $$(`.seg-tabs[data-seg="${group}"] .seg-btn`).forEach((b) =>
      b.classList.toggle("active", b.dataset.val === val)
    );
    $$(`.seg-pane[data-pane^="${group}-"]`).forEach((p) =>
      p.classList.toggle("active", p.dataset.pane === `${group}-${val}`)
    );
  }

  function bindDropzone(inputId, labelId, defaultText) {
    const input = $(`#${inputId}`);
    const label = $(`#${labelId}`);
    const dz = input.closest(".dropzone");

    const updateFileLabel = () => {
      if (input.files && input.files.length > 0) {
        const f = input.files[0];
        label.textContent = `${f.name} (${Math.max(1, Math.round(f.size / 1024))} KB)`;
        dz.classList.add("has-file");
      } else {
        label.textContent = defaultText;
        dz.classList.remove("has-file");
      }
    };

    input.addEventListener("change", updateFileLabel);
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("drag-over");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("drag-over");
      if (e.dataTransfer?.files?.length) {
        input.files = e.dataTransfer.files;
        updateFileLabel();
      }
    });
  }

  async function handleInitializeSession() {
    const fd = new FormData();
    fd.append("provider", state.settings.provider);
    fd.append("model", state.settings.model);
    fd.append("max_iterations", String(state.settings.maxIterations));
    fd.append("tailoring_mode", state.setupMode);

    // Template
    if (state.texSource === "upload") {
      const f = $("#input-tex-file").files?.[0];
      if (!f) return toast("Please upload a .tex template file.", "error");
      fd.append("tex_template", f);
    } else {
      fd.append("use_sample_template", "true");
    }

    // Resume
    if (state.resumeSource === "upload") {
      const f = $("#input-resume-file").files?.[0];
      if (!f) return toast("Please upload your base resume file.", "error");
      fd.append("resume_file", f);
    } else if (state.resumeSource === "paste") {
      const txt = $("#input-resume-text").value.trim();
      if (!txt) return toast("Please paste your resume text.", "error");
      fd.append("resume_text", txt);
    } else {
      const sid = $("#select-resume-sample").value;
      if (!sid) return toast("No sample resume available.", "error");
      fd.append("sample_preset", sid);
    }

    // JD
    if (state.jdSource === "upload") {
      const f = $("#input-jd-file").files?.[0];
      if (!f) return toast("Please upload a JD file.", "error");
      fd.append("jd_file", f);
    } else if (state.jdSource === "paste") {
      const txt = $("#input-jd-text").value.trim();
      if (!txt) return toast("Please enter job description text or URL.", "error");
      fd.append("jd_text", txt);
    } else {
      const sampleId = $("#select-jd-sample").value;
      const sample = state.samples.find((s) => s.id === sampleId);
      if (!sample) return toast("No sample JD selected.", "error");
      fd.append("jd_text", sample.jd_preview);
    }

    const btn = $("#btn-init-session");
    btn.disabled = true;
    $("#spinner-init").classList.remove("hidden");
    $("#text-init-btn").textContent = "Profiling Resume & JD...";

    try {
      const created = await apiFetch("/sessions", { method: "POST", body: fd });
      state.session = created;
      state.runMode = created.tailoring_mode || state.setupMode;
      renderAll();
      await refreshSessionsDrawer();
      toast(`Session ${created.session_id} initialized!`, "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
      $("#spinner-init").classList.add("hidden");
      $("#text-init-btn").textContent = "Initialize Workspace & Profile JD";
    }
  }

  function renderSetupSummary() {
    const s = state.session;
    const panel = $("#setup-summary-panel");
    const nextBtn = $("#setup-next-footer");
    if (!s) {
      panel.classList.add("hidden");
      nextBtn.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    nextBtn.classList.remove("hidden");

    const base = s.base_experience;
    $("#summary-candidate-name").textContent = base.candidate_name;
    $("#summary-exp-count").textContent = `${base.experiences.length} experience records`;

    $("#summary-experiences-list").innerHTML = base.experiences
      .map(
        (exp) => `
      <div class="exp-mini-card">
        <div class="exp-mini-head">
          <strong>${esc(exp.role_title)}</strong>
          <code>${esc(exp.id)}</code>
        </div>
        <div class="exp-mini-meta">${esc(exp.organization)} · ${esc(exp.start_date)} – ${esc(exp.end_date)}</div>
        <p class="small">${esc(exp.action)}</p>
        <div class="chip-row">
          ${(exp.verified_metrics || [])
            .map((m) => `<span class="chip chip-metric">${esc(m.value)} ${esc(m.context)}</span>`)
            .join("")}
          ${(exp.tools_and_components || [])
            .slice(0, 8)
            .map((t) => `<span class="chip">${esc(t)}</span>`)
            .join("")}
        </div>
      </div>`
      )
      .join("");

    const jd = s.parsed_jd;
    $("#summary-jd-title").textContent = jd.role_title;
    $("#summary-jd-meta").innerHTML = `
      <span class="badge badge-accent">${esc(jd.domain)}</span>
      <span class="badge badge-neutral">${esc(jd.seniority)}</span>
    `;

    const grouped = { must_have: [], preferred: [], implicit: [] };
    (jd.keywords || []).forEach((k) => {
      if (grouped[k.tier]) grouped[k.tier].push(k);
    });

    $("#summary-jd-keywords").innerHTML = `
      <div class="kw-tier-block">
        <div class="kw-tier-title">Metric Archetypes</div>
        <div class="chip-row">${(jd.metric_archetypes || []).map((m) => `<span class="chip">${esc(m)}</span>`).join("")}</div>
      </div>
      <div class="kw-tier-block">
        <div class="kw-tier-title">Tier 1 · Must-Have (${grouped.must_have.length})</div>
        <div class="chip-row">${grouped.must_have.map((k) => `<span class="badge badge-rose">${esc(k.term)}</span>`).join("")}</div>
      </div>
      <div class="kw-tier-block">
        <div class="kw-tier-title">Tier 2 · Preferred (${grouped.preferred.length})</div>
        <div class="chip-row">${grouped.preferred.map((k) => `<span class="badge badge-amber">${esc(k.term)}</span>`).join("")}</div>
      </div>
      <div class="kw-tier-block">
        <div class="kw-tier-title">Tier 3 · Implicit Signals (${grouped.implicit.length})</div>
        <div class="chip-row">${grouped.implicit.map((k) => `<span class="badge badge-neutral">${esc(k.term)}</span>`).join("")}</div>
      </div>
    `;
  }

  /* ==================== STEP 2: TAILOR & ATS ==================== */
  function syncRunModeButtons() {
    $$("[data-run-mode]").forEach((b) =>
      b.classList.toggle("active", b.dataset.runMode === state.runMode)
    );
    const runLabel = $("#text-run-btn");
    if (state.runMode === "hypothetical") {
      runLabel.textContent = "Generate Hypothetical Resume + Study Plan";
    } else {
      runLabel.textContent = "Run Grounded Tailoring & Verification";
    }
  }

  async function handleRunIteration() {
    const s = state.session;
    if (!s) return;

    const btn = $("#btn-run-iteration");
    btn.disabled = true;
    $("#spinner-run").classList.remove("hidden");

    const streamPanel = $("#stream-panel");
    const eventsList = $("#stream-events-list");
    streamPanel.classList.remove("hidden");
    eventsList.innerHTML = "";
    $("#stream-status-title").textContent =
      state.runMode === "hypothetical"
        ? `Running Hypothetical Shortlist Boost + Study Planner (Iteration ${s.iteration})...`
        : `Running Grounded Tailoring + Parallel ATS & NLI Audit (Iteration ${s.iteration})...`;

    const params = new URLSearchParams({
      provider: state.settings.provider,
      model: state.settings.model,
      tailoring_mode: state.runMode,
    });
    if (state.settings.apiKey.trim()) {
      // EventSource cannot set custom headers cleanly; fallback to POST /run when custom BYOK header is required
      try {
        addStreamLine("pipeline", `Running iteration ${s.iteration} (${state.runMode})...`);
        const updated = await apiFetch(`/sessions/${s.session_id}/run?${params.toString()}`, {
          method: "POST",
        });
        state.session = updated;
        addStreamLine("complete", "Tailoring, ATS scoring, and audit finished.");
        renderAll();
        await refreshSessionsDrawer();
        toast("Iteration complete!", "success");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        btn.disabled = false;
        $("#spinner-run").classList.add("hidden");
      }
      return;
    }

    const url = `/sessions/${s.session_id}/stream?${params.toString()}`;
    await new Promise((resolve) => {
      const es = new EventSource(url);
      const finish = () => {
        es.close();
        btn.disabled = false;
        $("#spinner-run").classList.add("hidden");
        resolve();
      };

      const onStage = (e) => {
        try {
          const payload = JSON.parse(e.data);
          addStreamLine(payload.stage || e.type, payload.message || "");
        } catch (_) {}
      };

      ["stage_started", "deterministic_completed", "agent_completed", "paused_for_hitl"].forEach((evtName) =>
        es.addEventListener(evtName, onStage)
      );

      es.addEventListener("state", async (e) => {
        state.session = JSON.parse(e.data);
        $("#stream-status-title").textContent = "Iteration complete!";
        renderAll();
        await refreshSessionsDrawer();
        toast(
          state.runMode === "hypothetical"
            ? "Hypothetical resume & Study Roadmap ready!"
            : "Grounded draft, ATS scorecard & NLI audit ready!",
          "success"
        );
        finish();
      });

      es.addEventListener("error", (e) => {
        let msg = "Pipeline execution error";
        if (e.data) {
          try {
            msg = JSON.parse(e.data).message || msg;
          } catch (_) {}
        }
        toast(msg, "error");
        $("#stream-status-title").textContent = "Run stopped with error";
        finish();
      });

      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) return;
        toast("Lost connection during stream.", "error");
        finish();
      };
    });
  }

  function addStreamLine(stage, message) {
    const list = $("#stream-events-list");
    const row = document.createElement("div");
    row.className = "stream-event";
    row.innerHTML = `<span class="stream-stage">${esc(stage)}</span><span>${esc(message)}</span>`;
    list.appendChild(row);
  }

  function renderTailorView() {
    const s = state.session;
    syncRunModeButtons();
    if (!s) return;

    $("#tailor-iteration-label").textContent = `Iteration ${s.iteration} / ${s.max_iterations}`;
    const scorecard = s.ats_scorecard;
    const tailored = s.tailored_resume;

    if (!scorecard || !tailored) {
      $("#ats-empty-card").classList.remove("hidden");
      $("#ats-results-stack").classList.add("hidden");
      $("#tailor-next-footer").classList.add("hidden");
      $("#resume-paper-sheet").innerHTML =
        '<div class="empty-state"><p class="muted">Run an iteration to preview your tailored resume here.</p></div>';
      $("#preview-latex-code").textContent = "";
      return;
    }

    $("#ats-empty-card").classList.add("hidden");
    $("#ats-results-stack").classList.remove("hidden");
    $("#tailor-next-footer").classList.remove("hidden");

    // Radial gauge
    const score = scorecard.overall_score;
    const circ = 2 * Math.PI * 50;
    const offset = circ * (1 - Math.max(0, Math.min(100, score)) / 100);
    const ring = $("#ats-ring-fg");
    ring.style.strokeDashoffset = String(offset);
    ring.style.stroke = score >= 75 ? "var(--emerald)" : score >= 55 ? "var(--accent)" : "var(--amber)";
    $("#ats-overall-score").textContent = String(score);

    const upliftBadge = $("#ats-uplift-badge");
    if (
      s.tailoring_mode === "hypothetical" &&
      typeof s.baseline_ats_score === "number" &&
      score !== s.baseline_ats_score
    ) {
      const diff = score - s.baseline_ats_score;
      upliftBadge.textContent = `${diff >= 0 ? "+" : ""}${diff} vs Grounded (${s.baseline_ats_score})`;
      upliftBadge.classList.remove("hidden");
    } else {
      upliftBadge.classList.add("hidden");
    }

    $("#val-kw-score").textContent = `${scorecard.keyword_score.toFixed(1)}%`;
    $("#bar-kw-score").style.width = `${scorecard.keyword_score}%`;
    $("#val-llm-score").textContent = `${scorecard.llm_recruiter_score}/100`;
    $("#bar-llm-score").style.width = `${scorecard.llm_recruiter_score}%`;
    $("#val-hyg-score").textContent = `${scorecard.hygiene_score.toFixed(1)}%`;
    $("#bar-hyg-score").style.width = `${scorecard.hygiene_score}%`;
    $("#val-tier1").textContent = `${scorecard.tier1_coverage_pct.toFixed(1)}%`;
    $("#val-tier2").textContent = `${scorecard.tier2_coverage_pct.toFixed(1)}%`;

    $("#ats-recruiter-notes").textContent = scorecard.llm_recruiter_notes;
    const warnBox = $("#ats-hygiene-warnings");
    if (scorecard.hygiene?.warnings?.length) {
      warnBox.classList.remove("hidden");
      warnBox.innerHTML = scorecard.hygiene.warnings.map((w) => `<div>• ${esc(w)}</div>`).join("");
    } else {
      warnBox.classList.add("hidden");
    }

    renderKeywordHeatmap();
    renderGapsList();
    renderResumePreview();
  }

  function renderKeywordHeatmap() {
    const heatmap = state.session?.ats_scorecard?.keyword_heatmap || [];
    const filtered = heatmap.filter((m) => {
      if (state.kwFilter === "matched") return m.status !== "missing";
      if (state.kwFilter === "missing") return m.status === "missing";
      return true;
    });

    $("#keyword-heatmap-grid").innerHTML = filtered
      .map((m) => {
        const cls =
          m.status === "exact_match" || m.status === "alias_match"
            ? "kw-exact"
            : m.status === "adjacent_match"
            ? "kw-adjacent"
            : "kw-missing";
        const via = m.matched_via ? ` via ${esc(m.matched_via)}` : "";
        const tierLabel = m.tier === "must_have" ? "T1" : m.tier === "preferred" ? "T2" : "T3";
        return `<span class="kw-chip ${cls}" title="${esc(m.status)}${via}">
          <span class="kw-tier-tag">${tierLabel}</span>
          <span>${esc(m.keyword)}${via ? ` <small>(${esc(m.matched_via)})</small>` : ""}</span>
        </span>`;
      })
      .join("");
  }

  function renderGapsList() {
    const gaps = state.session?.ats_scorecard?.gaps || [];
    const container = $("#ats-gaps-list");
    if (!gaps.length) {
      container.innerHTML = '<p class="muted small">Zero missing must-have or preferred gaps detected.</p>';
      return;
    }

    container.innerHTML = gaps
      .map((g, idx) => {
        const isFraming = g.gap_type === "framing_gap";
        return `
        <div class="gap-row">
          <div class="gap-row-info">
            <div>
              <strong>${esc(g.keyword)}</strong>
              <span class="badge ${g.tier === "must_have" ? "badge-rose" : "badge-amber"}">${esc(g.tier)}</span>
              <span class="badge ${isFraming ? "badge-accent" : "badge-violet"}">${isFraming ? "Framing Gap" : "Hard Tool Gap"}</span>
            </div>
            ${
              g.suggested_source_exp_id
                ? `<span class="muted small">Evidence in <code>${esc(g.suggested_source_exp_id)}</code></span>`
                : '<span class="muted small">Not present in BaseExperience — study candidate</span>'
            }
          </div>
          ${
            isFraming
              ? `<button type="button" class="btn btn-ghost btn-sm" data-gap-surface="${idx}">+ Surface</button>`
              : `<button type="button" class="btn btn-secondary btn-sm" data-gap-learn="${idx}">+ Study Queue</button>`
          }
        </div>`;
      })
      .join("");

    container.querySelectorAll("[data-gap-surface]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const g = gaps[Number(btn.dataset.gapSurface)];
        state.queuedSurfaceGaps.add(g.keyword);
        renderHitlActions();
        setStep("audit");
        selectHitlTab("REJECT");
        toast(`Queued "${g.keyword}" to surface in the next draft.`);
      });
    });

    container.querySelectorAll("[data-gap-learn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const g = gaps[Number(btn.dataset.gapLearn)];
        try {
          const updated = await apiFetch(`/sessions/${state.session.session_id}/hitl`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "ACCEPT_AND_LEARN",
              to_learn_items: [
                {
                  topic_or_claim: g.keyword,
                  source: "hard_tool_gap",
                  priority: g.tier === "must_have" ? "high" : "medium",
                  context_note: `Missing ${g.tier} requirement identified in ATS gap analysis.`,
                },
              ],
            }),
          });
          state.session = updated;
          renderAll();
          toast(`Added "${g.keyword}" to Study Queue.`, "success");
        } catch (err) {
          toast(err.message, "error");
        }
      });
    });
  }

  function formatBulletText(text) {
    return esc(text).replace(
      /(\[ADD\s+METRIC:[^\]]*\])/gi,
      '<span class="rp-placeholder-chip">$1</span>'
    );
  }

  function renderResumePreview() {
    const s = state.session;
    const t = s?.tailored_resume;
    if (!t) return;

    $("#preview-latex-code").textContent = t.rendered_tex || "";

    const auditByBullet = new Map();
    (s.critic_report?.audits || []).forEach((a) => {
      if (a.bullet_id) auditByBullet.set(a.bullet_id, a);
    });

    let hypoCount = 0;
    const renderEntryBlock = (entry) => `
      <div class="rp-entry">
        <div class="rp-entry-head">
          <span>${esc(entry.role_title)} — ${esc(entry.organization)}</span>
          <span class="rp-entry-dates">${esc(entry.date_range)}</span>
        </div>
        <ul class="rp-bullets">
          ${(entry.bullets || [])
            .map((b) => {
              const audit = auditByBullet.get(b.bullet_id);
              const isHypo =
                Boolean(b.is_hypothetical) ||
                (b.hypothetical_additions && b.hypothetical_additions.length > 0) ||
                (s.tailoring_mode === "hypothetical" && audit && audit.verdict !== "SUPPORTED");
              const isUnsupGrounded =
                s.tailoring_mode === "grounded" && audit && audit.verdict === "UNSUPPORTED";
              if (isHypo) hypoCount += 1;
              const liClass = isHypo ? "is-hypo-bullet" : isUnsupGrounded ? "is-unsupported-bullet" : "";
              const adds = (b.hypothetical_additions || []).join(", ");
              const hypoTag = isHypo
                ? `<span class="rp-hypo-tag" title="${esc(adds || "Hypothetical enhancement")}">HYPOTHETICAL${adds ? `: ${esc(adds)}` : ""}</span>`
                : "";
              return `<li class="${liClass}"><span class="rp-prov">${esc(b.source_experience_id)}</span>${formatBulletText(b.text)}${hypoTag}</li>`;
            })
            .join("")}
        </ul>
      </div>`;

    const base = s.base_experience;
    const contact = (base.contact_lines || []).map((c) => esc(c)).join(" · ");
    const skillsHtml = Object.entries(t.skills_grouped || {})
      .filter(([, vals]) => vals && vals.length)
      .map(
        ([grp, vals]) =>
          `<div class="rp-skills-line"><strong>${esc(grp)}:</strong> ${vals.map(esc).join(", ")}</div>`
      )
      .join("");

    const eduHtml = (base.education || [])
      .map((e) => {
        const deg = e.degree || "";
        const inst = e.institution || e.school || "";
        const dt = e.dates || e.year || "";
        return `<div class="rp-entry-head" style="font-weight:500;"><span><strong>${esc(deg)}</strong>${deg && inst ? " — " : ""}${esc(inst)}</span><span class="rp-entry-dates">${esc(dt)}</span></div>`;
      })
      .join("");

    const customHtml = Object.entries(t.custom_sections || {})
      .filter(([, entries]) => entries && entries.length)
      .map(
        ([sec, entries]) =>
          `<div class="rp-sec-title">${esc(sec)}</div>${entries.map(renderEntryBlock).join("")}`
      )
      .join("");

    $("#resume-paper-sheet").innerHTML = `
      <div class="rp-header">
        <div class="rp-name">${esc(base.candidate_name)}</div>
        ${contact ? `<div class="rp-contact">${contact}</div>` : ""}
      </div>
      ${t.summary ? `<div class="rp-sec-title">Summary</div><p>${esc(t.summary)}</p>` : ""}
      ${t.experience_entries?.length ? `<div class="rp-sec-title">Experience</div>${t.experience_entries.map(renderEntryBlock).join("")}` : ""}
      ${t.project_entries?.length ? `<div class="rp-sec-title">Projects</div>${t.project_entries.map(renderEntryBlock).join("")}` : ""}
      ${customHtml}
      ${skillsHtml ? `<div class="rp-sec-title">Skills</div>${skillsHtml}` : ""}
      ${eduHtml ? `<div class="rp-sec-title">Education</div>${eduHtml}` : ""}
    `;

    const hypoBadge = $("#preview-hypo-count");
    if (hypoCount > 0) {
      hypoBadge.textContent = `${hypoCount} Hypothetical Bullet(s) — See Study Plan`;
      hypoBadge.classList.remove("hidden");
    } else {
      hypoBadge.classList.add("hidden");
    }
  }

  /* ==================== STEP 3: AUDIT & HITL ==================== */
  function renderAuditView() {
    const s = state.session;
    const critic = s?.critic_report;
    if (!critic) return;

    const audits = critic.audits || [];
    const sup = audits.filter((a) => a.verdict === "SUPPORTED").length;
    $("#kpi-audit-total").textContent = String(audits.length);
    $("#kpi-audit-supported").textContent = String(sup);
    $("#kpi-audit-stretched").textContent = String(critic.stretched_count);
    $("#kpi-audit-unsupported").textContent = String(critic.unsupported_count);

    const q = state.auditSearch.trim().toLowerCase();
    const filtered = audits.filter((a) => {
      if (state.auditFilter !== "ALL" && a.verdict !== state.auditFilter) return false;
      if (q && !a.claim_text.toLowerCase().includes(q) && !(a.reasoning || "").toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });

    const container = $("#audit-claims-list");
    container.innerHTML = filtered.length
      ? filtered
          .map((a, idx) => {
            const vCls =
              a.verdict === "SUPPORTED"
                ? "badge-emerald"
                : a.verdict === "STRETCHED"
                ? "badge-amber"
                : "badge-rose";
            const phrase = a.flagged_phrase || a.claim_text;
            return `
            <div class="audit-claim-card">
              <div class="audit-claim-head">
                <div class="inline-badges">
                  <span class="badge badge-neutral">${esc(a.target_type.toUpperCase())}</span>
                  ${a.source_experience_id ? `<code>${esc(a.source_experience_id)}</code>` : ""}
                  ${a.bullet_id ? `<code>${esc(a.bullet_id)}</code>` : ""}
                </div>
                <span class="badge ${vCls}">${esc(a.verdict)}</span>
              </div>
              <div class="audit-claim-text">${esc(a.claim_text)}</div>
              <div class="audit-claim-reason">${esc(a.reasoning)}</div>
              ${a.flagged_phrase ? `<span class="audit-flagged">Flagged: ${esc(a.flagged_phrase)}</span>` : ""}
              ${
                a.verdict !== "SUPPORTED"
                  ? `<div class="audit-quick-actions">
                      <button type="button" class="btn btn-ghost btn-sm" data-quick-reject="${esc(phrase)}">Reject &amp; Tone Down</button>
                      <button type="button" class="btn btn-secondary btn-sm" data-quick-learn="${idx}">+ Add to Study Queue</button>
                    </div>`
                  : ""
              }
            </div>`;
          })
          .join("")
      : '<p class="muted small">No claims match the current filter.</p>';

    container.querySelectorAll("[data-quick-reject]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.queuedRejectClaims.add(btn.dataset.quickReject);
        renderHitlActions();
        selectHitlTab("REJECT");
      });
    });
    container.querySelectorAll("[data-quick-learn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const a = filtered[Number(btn.dataset.quickLearn)];
        try {
          const updated = await apiFetch(`/sessions/${s.session_id}/hitl`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "ACCEPT_AND_LEARN",
              to_learn_items: [
                {
                  topic_or_claim: a.flagged_phrase || a.claim_text,
                  source: s.tailoring_mode === "hypothetical" ? "hypothetical_addition" : "accepted_stretch",
                  priority: "high",
                  context_note: a.reasoning,
                },
              ],
            }),
          });
          state.session = updated;
          renderAll();
          toast("Added claim to Study Queue.", "success");
        } catch (err) {
          toast(err.message, "error");
        }
      });
    });

    renderHitlActions();
  }

  function selectHitlTab(tabName) {
    state.hitlTab = tabName;
    $$("#hitl-action-tabs .hitl-tab").forEach((b) =>
      b.classList.toggle("active", b.dataset.hitl === tabName)
    );
    $$(".hitl-pane").forEach((p) =>
      p.classList.toggle("active", p.dataset.hitlPane === tabName)
    );
  }

  function renderHitlActions() {
    const s = state.session;
    if (!s || !s.critic_report) return;

    const unresolved = s.ats_scorecard?.hygiene?.unresolved_placeholders || [];
    const unsup = s.critic_report.unsupported_count;
    const isHypo = s.tailoring_mode === "hypothetical";
    const hasStudyPlan = Boolean(s.study_plan);

    const truthOk = isHypo ? hasStudyPlan : unsup === 0;
    const phOk = unresolved.length === 0;
    $("#approve-gate-checklist").innerHTML = `
      <div class="gate-row">
        <span>Active Strategy</span>
        <span class="badge ${isHypo ? "badge-violet" : "badge-emerald"}">${isHypo ? "Hypothetical Boost" : "Grounded Truth"}</span>
      </div>
      <div class="gate-row">
        <span>${isHypo ? "Study Plan Generated" : "Zero Unsupported Claims"}</span>
        <span class="badge ${truthOk ? "badge-emerald" : "badge-rose"}">${
          isHypo ? (hasStudyPlan ? "Ready" : "Missing") : `${unsup} remaining`
        }</span>
      </div>
      <div class="gate-row">
        <span>Unresolved [ADD METRIC] Placeholders</span>
        <span class="badge ${phOk ? "badge-emerald" : "badge-rose"}">${unresolved.length}</span>
      </div>
    `;
    $("#btn-hitl-approve").disabled = !(truthOk && phOk);

    // Reject checklists
    const flagged = (s.critic_report.audits || [])
      .filter((a) => a.verdict !== "SUPPORTED")
      .map((a) => a.flagged_phrase || a.claim_text);
    $("#reject-claims-checklist").innerHTML = flagged.length
      ? flagged
          .map(
            (c) => `
          <label class="check-row">
            <input type="checkbox" class="chk-reject-claim" value="${esc(c)}" ${state.queuedRejectClaims.has(c) ? "checked" : ""} />
            <span>${esc(c)}</span>
          </label>`
          )
          .join("")
      : '<span class="muted small">No flagged claims.</span>';

    const framingGaps = (s.ats_scorecard?.gaps || []).filter((g) => g.gap_type === "framing_gap");
    $("#reject-gaps-checklist").innerHTML = framingGaps.length
      ? framingGaps
          .map(
            (g) => `
          <label class="check-row">
            <input type="checkbox" class="chk-surface-gap" value="${esc(g.keyword)}" ${state.queuedSurfaceGaps.has(g.keyword) ? "checked" : ""} />
            <span>${esc(g.keyword)} <small class="muted">(${esc(g.suggested_source_exp_id || "base")})</small></span>
          </label>`
          )
          .join("")
      : '<span class="muted small">No framing gaps left to surface.</span>';

    // Direct Edit form
    const t = s.tailored_resume;
    if (t) {
      let editHtml = `
        <div>
          <label class="field-label" for="edit-summary-input">Summary</label>
          <textarea id="edit-summary-input" class="textarea" rows="3">${esc(t.summary || "")}</textarea>
        </div>`;
      (t.experience_entries || []).forEach((entry, ei) => {
        editHtml += `<div class="field-label">${esc(entry.role_title)} @ ${esc(entry.organization)}</div>`;
        (entry.bullets || []).forEach((b, bi) => {
          editHtml += `<textarea class="textarea edit-bullet-input" rows="2" data-section="exp" data-ei="${ei}" data-bi="${bi}">${esc(b.text)}</textarea>`;
        });
      });
      (t.project_entries || []).forEach((entry, ei) => {
        editHtml += `<div class="field-label">Project: ${esc(entry.role_title)} (${esc(entry.organization)})</div>`;
        (entry.bullets || []).forEach((b, bi) => {
          editHtml += `<textarea class="textarea edit-bullet-input" rows="2" data-section="proj" data-ei="${ei}" data-bi="${bi}">${esc(b.text)}</textarea>`;
        });
      });
      $("#direct-edit-form").innerHTML = editHtml;
    }

    // Verify & Promote select
    const expSelect = $("#promote-exp-id");
    expSelect.innerHTML = (s.base_experience?.experiences || [])
      .map((e) => `<option value="${esc(e.id)}">[${esc(e.id)}] ${esc(e.role_title)} @ ${esc(e.organization)}</option>`)
      .join("");
  }

  async function callHitl(payload) {
    const s = state.session;
    if (!s) return;
    const params = new URLSearchParams({
      provider: state.settings.provider,
      model: state.settings.model,
    });
    const updated = await apiFetch(`/sessions/${s.session_id}/hitl?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.session = updated;
    renderAll();
    await refreshSessionsDrawer();
    return updated;
  }

  /* ==================== STEP 4: STUDY PLAN & EXPORT ==================== */
  function renderStudyView() {
    const s = state.session;
    if (!s) return;

    const plan = s.study_plan;
    const switchBtn = $("#btn-switch-hypothetical-here");
    switchBtn.classList.toggle("hidden", s.tailoring_mode === "hypothetical");

    if (!plan) {
      $("#study-stats-strip").classList.add("hidden");
      $("#study-deltas-card").classList.add("hidden");
      $("#study-controls-bar").classList.add("hidden");
      $("#link-download-study-md").classList.add("hidden");
      $("#study-hero-title").textContent = "Personalized Study & Interview Prep Roadmap";
      $("#study-hero-summary").textContent =
        s.tailoring_mode === "grounded"
          ? "You are in Grounded Mode. Generate a study plan from your ATS gaps & To-Learn queue, or switch to Hypothetical Shortlist Mode to build an aspirational resume with a full learning checklist."
          : "Run an iteration in Hypothetical Mode to automatically build your study roadmap.";
      $("#study-cards-container").innerHTML = `
        <div class="card" style="grid-column: 1 / -1;">
          <div class="empty-state">
            <div class="empty-icon">✦</div>
            <h3>No Study Plan Generated Yet</h3>
            <p class="muted">
              Click <strong>Boost Resume (Hypothetical Mode)</strong> to generate a shortlist-maximizing resume paired with every topic you need to study, or generate a study plan from your current gaps.
            </p>
          </div>
        </div>`;
      renderExportCenter();
      return;
    }

    $("#study-stats-strip").classList.remove("hidden");
    $("#study-controls-bar").classList.remove("hidden");

    const mdLink = $("#link-download-study-md");
    mdLink.href = `/sessions/${s.session_id}/artifacts/StudyPlan.md`;
    mdLink.classList.remove("hidden");

    $("#study-hero-title").textContent = `Study Roadmap · ${plan.target_role}`;
    $("#study-hero-summary").textContent = plan.shortlist_boost_summary;

    const items = plan.study_items || [];
    const studiedCount = items.filter((i) => i.studied).length;
    const pct = items.length ? Math.round((studiedCount / items.length) * 100) : 0;
    $("#study-progress-text").textContent = `${studiedCount} / ${items.length}`;
    $("#study-progress-bar").style.width = `${pct}%`;
    $("#study-total-hours").textContent = `${plan.estimated_total_hours.toFixed(1)} hrs`;
    $("#study-deltas-count").textContent = String((plan.hypothetical_deltas || []).length);
    $("#study-queue-count").textContent = String((s.to_learn_queue || []).length);

    // Deltas
    const deltasCard = $("#study-deltas-card");
    if (plan.hypothetical_deltas?.length) {
      deltasCard.classList.remove("hidden");
      $("#study-deltas-list").innerHTML = plan.hypothetical_deltas
        .map(
          (d) => `
        <div class="delta-row">
          <div class="delta-head">
            <div class="inline-badges">
              <span class="badge badge-violet">${esc(d.target_type.toUpperCase())}</span>
              <code>${esc(d.location)}</code>
            </div>
            <span class="badge badge-accent">Bridges: ${esc(d.gap_addressed)}</span>
          </div>
          <div class="delta-claim">${esc(d.added_or_upgraded_claim)}</div>
          <div class="muted small">${esc(d.rationale)}</div>
        </div>`
        )
        .join("");
    } else {
      deltasCard.classList.add("hidden");
    }

    // Filtered study cards
    const filteredItems = items.filter((item) => {
      if (state.studyFilter === "pending") return !item.studied;
      if (["high", "medium", "low"].includes(state.studyFilter)) return item.priority === state.studyFilter;
      return true;
    });

    const container = $("#study-cards-container");
    container.innerHTML = filteredItems.length
      ? filteredItems
          .map((item) => {
            const pCls =
              item.priority === "high"
                ? "badge-rose"
                : item.priority === "medium"
                ? "badge-amber"
                : "badge-neutral";
            return `
          <article class="card study-item-card ${item.studied ? "is-studied" : ""}">
            <div class="study-item-head">
              <label class="study-check-label">
                <input type="checkbox" class="study-checkbox" data-study-id="${esc(item.id)}" ${item.studied ? "checked" : ""} />
                <div>
                  <h3>${esc(item.topic)}</h3>
                  <span class="muted small">${esc(item.where_it_appears)}</span>
                </div>
              </label>
              <div class="inline-badges">
                <span class="badge ${pCls}">${esc(item.priority.toUpperCase())}</span>
                <span class="badge badge-neutral">${item.estimated_hours.toFixed(1)}h</span>
              </div>
            </div>

            <div class="study-claim-quote">
              <span class="study-section-label">Resume Claim to Defend</span>
              “${esc(item.resume_claim_to_defend)}”
            </div>

            ${
              item.subtopics_to_study?.length
                ? `<div>
                    <span class="study-section-label">What to Study</span>
                    <ul class="study-sub-list">${item.subtopics_to_study.map((sub) => `<li>${esc(sub)}</li>`).join("")}</ul>
                  </div>`
                : ""
            }

            <div class="study-lab-box">
              <span class="study-section-label">Hands-On Practice Exercise</span>
              <div>${esc(item.hands_on_exercise)}</div>
            </div>

            ${
              item.likely_interview_questions?.length
                ? `<div>
                    <span class="study-section-label">Likely Interview Questions</span>
                    <ul class="study-sub-list">${item.likely_interview_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
                  </div>`
                : ""
            }

            ${
              item.recommended_resources?.length
                ? `<div class="chip-row">${item.recommended_resources.map((r) => `<span class="chip">${esc(r)}</span>`).join("")}</div>`
                : ""
            }
          </article>`;
          })
          .join("")
      : '<div class="card" style="grid-column:1/-1;"><div class="empty-state"><p class="muted">No topics match this filter.</p></div></div>';

    container.querySelectorAll(".study-checkbox").forEach((chk) => {
      chk.addEventListener("change", async () => {
        const itemId = chk.dataset.studyId;
        try {
          const updated = await apiFetch(`/sessions/${s.session_id}/study-plan/${itemId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ studied: chk.checked }),
          });
          state.session = updated;
          renderStudyView();
          syncStepperLocks();
        } catch (err) {
          chk.checked = !chk.checked;
          toast(err.message, "error");
        }
      });
    });

    renderExportCenter();
  }

  function renderExportCenter() {
    const s = state.session;
    const grid = $("#export-artifacts-grid");
    const badge = $("#export-status-badge");
    if (!s) return;

    badge.textContent = s.approved ? "Approved & Exported" : s.status;
    badge.className = `badge ${s.approved ? "badge-emerald" : "badge-neutral"}`;

    const sid = s.session_id;
    const tiles = [];

    if (s.approved) {
      tiles.push(`
        <div class="export-tile">
          <div><strong>tailored_resume.tex</strong><p class="muted small">Ready for Overleaf or local LaTeX compiler.</p></div>
          <a class="btn btn-primary btn-sm" href="/sessions/${sid}/artifacts/tailored_resume.tex" download="tailored_resume.tex">Download .tex</a>
        </div>`);

      if (state.config?.pdf_compiler) {
        tiles.push(`
          <div class="export-tile">
            <div><strong>tailored_resume.pdf</strong><p class="muted small">Compiled via ${esc(state.config.pdf_compiler)}.</p></div>
            <a class="btn btn-ghost btn-sm" href="/sessions/${sid}/artifacts/tailored_resume.pdf" download="tailored_resume.pdf">Download .pdf</a>
          </div>`);
      } else {
        tiles.push(`
          <div class="export-tile">
            <div><strong>PDF Resume (Print)</strong><p class="muted small">No local TeX compiler found — save cleanly via browser Print.</p></div>
            <button type="button" class="btn btn-ghost btn-sm" id="btn-export-print-pdf">Print / Save PDF</button>
          </div>`);
      }

      tiles.push(`
        <div class="export-tile">
          <div><strong>ToLearnQueue.json</strong><p class="muted small">Phase 2 interview prep queue (${s.to_learn_queue.length} items).</p></div>
          <a class="btn btn-ghost btn-sm" href="/sessions/${sid}/artifacts/ToLearnQueue.json" download="ToLearnQueue.json">Download JSON</a>
        </div>`);
    } else {
      tiles.push(`
        <div class="export-tile">
          <div><strong>Approve Draft First</strong><p class="muted small">Complete the Stage 3 Gate to unlock final <code>tailored_resume.tex</code> exports.</p></div>
          <button type="button" class="btn btn-primary btn-sm" id="btn-export-goto-audit">Go to Audit &amp; Gate</button>
        </div>`);
    }

    if (s.study_plan) {
      tiles.push(`
        <div class="export-tile">
          <div><strong>StudyPlan.md</strong><p class="muted small">Printable Markdown checklist &amp; interview Q&amp;A.</p></div>
          <a class="btn btn-secondary btn-sm" href="/sessions/${sid}/artifacts/StudyPlan.md" download="StudyPlan.md">Download Markdown</a>
        </div>`);
    }

    grid.innerHTML = tiles.join("");
    $("#btn-export-print-pdf")?.addEventListener("click", () => {
      setStep("tailor");
      setTimeout(() => window.print(), 100);
    });
    $("#btn-export-goto-audit")?.addEventListener("click", () => setStep("audit"));
  }

  /* ==================== SESSIONS DRAWER ==================== */
  async function refreshSessionsDrawer() {
    try {
      const data = await apiFetch("/sessions/summaries");
      const list = data.sessions || [];
      $("#sessions-count-chip").textContent = String(list.length);
      const container = $("#sessions-drawer-list");

      if (!list.length) {
        container.innerHTML = '<p class="muted small">No saved sessions yet. Initialize one in Step 1.</p>';
        return;
      }

      container.innerHTML = list
        .map((item) => {
          const active = state.session && state.session.session_id === item.session_id;
          const modeCls = item.tailoring_mode === "hypothetical" ? "badge-violet" : "badge-emerald";
          return `
          <div class="session-item ${active ? "is-active" : ""}">
            <div class="session-item-top">
              <strong>${esc(item.candidate_name)}</strong>
              <span class="badge ${modeCls}">${esc(item.tailoring_mode)}</span>
            </div>
            <div class="small">${esc(item.role_title)} · <span class="muted">${esc(item.domain)}</span></div>
            <div class="inline-badges">
              <span class="badge badge-neutral">${esc(item.status)}</span>
              ${item.overall_score != null ? `<span class="badge badge-accent">ATS ${item.overall_score}/100</span>` : ""}
              ${item.study_items_count ? `<span class="badge badge-violet">${item.study_items_count} Study Topics</span>` : ""}
            </div>
            <div class="session-item-actions">
              <button type="button" class="btn btn-ghost btn-sm" data-del-sid="${esc(item.session_id)}">Delete</button>
              <button type="button" class="btn btn-primary btn-sm" data-load-sid="${esc(item.session_id)}">Open</button>
            </div>
          </div>`;
        })
        .join("");

      container.querySelectorAll("[data-load-sid]").forEach((btn) => {
        btn.addEventListener("click", () => loadSession(btn.dataset.loadSid));
      });
      container.querySelectorAll("[data-del-sid]").forEach((btn) => {
        btn.addEventListener("click", () => deleteSession(btn.dataset.delSid));
      });
    } catch (_) {}
  }

  async function loadSession(sid) {
    try {
      const loaded = await apiFetch(`/sessions/${sid}`);
      state.session = loaded;
      state.runMode = loaded.tailoring_mode || "grounded";
      state.queuedRejectClaims.clear();
      state.queuedSurfaceGaps.clear();
      closeSessionsDrawer();
      renderAll();
      if (loaded.study_plan && loaded.tailoring_mode === "hypothetical") {
        setStep("tailor");
      } else if (loaded.tailored_resume) {
        setStep("tailor");
      } else {
        setStep("setup");
      }
      toast(`Loaded session ${sid}`, "success");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function deleteSession(sid) {
    try {
      await apiFetch(`/sessions/${sid}`, { method: "DELETE" });
      if (state.session?.session_id === sid) {
        state.session = null;
        renderAll();
        setStep("setup");
      }
      await refreshSessionsDrawer();
      toast(`Deleted session ${sid}`);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function openSessionsDrawer() {
    $("#sessions-backdrop").classList.remove("hidden");
    $("#sessions-drawer").classList.remove("hidden");
    refreshSessionsDrawer();
  }
  function closeSessionsDrawer() {
    $("#sessions-backdrop").classList.add("hidden");
    $("#sessions-drawer").classList.add("hidden");
  }

  /* ==================== GLOBAL RENDER & EVENTS ==================== */
  function renderAll() {
    updateHeaderFromSession();
    syncStepperLocks();
    renderSetupSummary();
    renderTailorView();
    renderAuditView();
    renderStudyView();
  }

  function bindEvents() {
    $("#btn-toggle-theme").addEventListener("click", toggleTheme);

    // Stepper navigation
    $$(".step-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!btn.disabled) setStep(btn.dataset.step);
      });
    });

    $("#btn-goto-tailor").addEventListener("click", () => setStep("tailor"));
    $("#btn-goto-audit").addEventListener("click", () => setStep("audit"));
    $("#btn-goto-study-from-tailor").addEventListener("click", () => setStep("study"));

    // Setup mode cards
    $$(".mode-card").forEach((card) => {
      card.addEventListener("click", () => {
        state.setupMode = card.dataset.modeCard;
        state.runMode = state.setupMode;
        $$(".mode-card").forEach((c) => c.classList.toggle("selected", c === card));
        updateHeaderFromSession();
        syncRunModeButtons();
      });
    });

    // Segmented tabs
    $$(".seg-tabs").forEach((group) => {
      const seg = group.dataset.seg;
      group.querySelectorAll(".seg-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (seg === "preview") {
            group.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
            $("#preview-formatted-pane").classList.toggle("hidden", btn.dataset.val !== "formatted");
            $("#preview-latex-pane").classList.toggle("hidden", btn.dataset.val !== "latex");
          } else {
            setSegment(seg, btn.dataset.val);
          }
        });
      });
    });

    $("#select-jd-sample").addEventListener("change", (e) => {
      const sample = state.samples.find((s) => s.id === e.target.value);
      $("#preview-jd-sample").value = sample ? sample.jd_preview : "";
    });

    bindDropzone("input-resume-file", "label-resume-file", "Drop PDF, DOCX, YAML, JSON, or TXT");
    bindDropzone("input-tex-file", "label-tex-file", "Drop your Overleaf .tex template");
    bindDropzone("input-jd-file", "label-jd-file", "Drop JD file (.txt, .pdf, .docx)");

    $("#btn-init-session").addEventListener("click", handleInitializeSession);

    // Run mode inline switch
    $$("[data-run-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.runMode = btn.dataset.runMode;
        syncRunModeButtons();
      });
    });
    $("#btn-run-iteration").addEventListener("click", handleRunIteration);

    // Preview Copy & Print
    $("#btn-copy-tex").addEventListener("click", async () => {
      const tex = state.session?.tailored_resume?.rendered_tex || "";
      if (!tex) return toast("No LaTeX rendered yet.", "error");
      await navigator.clipboard.writeText(tex);
      toast("Copied LaTeX source to clipboard.", "success");
    });
    $("#btn-print-resume").addEventListener("click", () => window.print());

    // Heatmap & Audit & Study filters
    $$("#kw-filter-pills .pill-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.kwFilter = btn.dataset.kwFilter;
        $$("#kw-filter-pills .pill-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderKeywordHeatmap();
      });
    });
    $$("#audit-filter-pills .pill-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.auditFilter = btn.dataset.auditFilter;
        $$("#audit-filter-pills .pill-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderAuditView();
      });
    });
    $("#audit-search-input").addEventListener("input", (e) => {
      state.auditSearch = e.target.value;
      renderAuditView();
    });
    $$("#study-priority-filters .pill-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.studyFilter = btn.dataset.studyFilter;
        $$("#study-priority-filters .pill-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderStudyView();
      });
    });

    // HITL tabs & actions
    $$("#hitl-action-tabs .hitl-tab").forEach((btn) => {
      btn.addEventListener("click", () => selectHitlTab(btn.dataset.hitl));
    });

    $("#btn-hitl-approve").addEventListener("click", async () => {
      try {
        await callHitl({ action: "APPROVE" });
        setStep("study");
        toast("Resume approved and exported!", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });

    $("#btn-hitl-reject").addEventListener("click", async () => {
      const rejected = $$(".chk-reject-claim:checked").map((c) => c.value);
      const surface = $$(".chk-surface-gap:checked").map((c) => c.value);
      const instr = $("#reject-instructions")
        .value.split("\n")
        .map((x) => x.trim())
        .filter(Boolean);
      try {
        await callHitl({
          action: "REJECT",
          rejected_claims: rejected,
          missing_tier1_to_surface: surface,
          user_instructions: instr,
        });
        state.queuedRejectClaims.clear();
        state.queuedSurfaceGaps.clear();
        setStep("tailor");
        toast("Revision feedback saved. Run next iteration in Step 2.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });

    $("#btn-hitl-direct-edit").addEventListener("click", async () => {
      const copy = JSON.parse(JSON.stringify(state.session.tailored_resume));
      copy.summary = $("#edit-summary-input").value;
      $$(".edit-bullet-input").forEach((ta) => {
        const ei = Number(ta.dataset.ei);
        const bi = Number(ta.dataset.bi);
        const list = ta.dataset.section === "proj" ? copy.project_entries : copy.experience_entries;
        if (list?.[ei]?.bullets?.[bi]) {
          list[ei].bullets[bi].text = ta.value;
        }
      });
      try {
        await callHitl({ action: "DIRECT_EDIT", edited_tailored_resume: copy });
        toast("Direct edits applied and re-audited.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });

    $("#btn-hitl-promote").addEventListener("click", async () => {
      const expId = $("#promote-exp-id").value;
      const val = $("#promote-metric-val").value.trim();
      const ctx = $("#promote-metric-ctx").value.trim();
      const skill = $("#promote-skill").value.trim();
      const payload = {
        action: "VERIFY_AND_PROMOTE",
        promoted_metrics: val && ctx ? { [expId]: [{ value: val, context: ctx }] } : {},
        promoted_skills: skill ? [skill] : [],
      };
      try {
        await callHitl(payload);
        $("#promote-metric-val").value = "";
        $("#promote-metric-ctx").value = "";
        $("#promote-skill").value = "";
        toast("Verified facts promoted and re-audited.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });

    $("#btn-hitl-learn").addEventListener("click", async () => {
      const topic = $("#learn-topic").value.trim();
      if (!topic) return toast("Enter a topic or claim to learn.", "error");
      try {
        await callHitl({
          action: "ACCEPT_AND_LEARN",
          to_learn_items: [
            {
              topic_or_claim: topic,
              source: $("#learn-source").value,
              priority: $("#learn-priority").value,
              context_note: $("#learn-note").value.trim() || "Added during HITL review.",
            },
          ],
        });
        $("#learn-topic").value = "";
        $("#learn-note").value = "";
        toast(`Added "${topic}" to Study Queue.`, "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });

    // Step 4 Study Plan actions
    $("#btn-generate-study-plan").addEventListener("click", async () => {
      if (!state.session) return;
      const btn = $("#btn-generate-study-plan");
      btn.disabled = true;
      $("#spinner-study").classList.remove("hidden");
      $("#text-study-btn").textContent = "Generating Study Plan...";
      try {
        const params = new URLSearchParams({
          provider: state.settings.provider,
          model: state.settings.model,
        });
        const updated = await apiFetch(
          `/sessions/${state.session.session_id}/study-plan?${params.toString()}`,
          { method: "POST" }
        );
        state.session = updated;
        renderAll();
        toast("Study Roadmap updated!", "success");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        btn.disabled = false;
        $("#spinner-study").classList.add("hidden");
        $("#text-study-btn").textContent = "Generate / Refresh Study Plan";
      }
    });

    $("#btn-switch-hypothetical-here").addEventListener("click", async () => {
      state.runMode = "hypothetical";
      setStep("tailor");
      await handleRunIteration();
      if (state.session?.study_plan) setStep("study");
    });

    // Drawers & Modals
    $("#btn-open-sessions").addEventListener("click", openSessionsDrawer);
    $("#btn-close-sessions").addEventListener("click", closeSessionsDrawer);
    $("#sessions-backdrop").addEventListener("click", closeSessionsDrawer);

    $("#btn-open-settings").addEventListener("click", () => {
      updateSettingsUI();
      $("#settings-modal-backdrop").classList.remove("hidden");
    });
    $("#btn-close-settings").addEventListener("click", () =>
      $("#settings-modal-backdrop").classList.add("hidden")
    );
    $("#cfg-provider").addEventListener("change", (e) => {
      const defaults = state.config?.default_models || {
        gemini: "gemini-3.8-flash",
        claude: "claude-3-5-haiku-latest",
        ollama: "llama3.1",
      };
      $("#cfg-model").value = defaults[e.target.value] || "";
    });
    $("#btn-save-settings").addEventListener("click", () => {
      state.settings.provider = $("#cfg-provider").value;
      state.settings.model = $("#cfg-model").value.trim() || "gemini-3.8-flash";
      state.settings.apiKey = $("#cfg-api-key").value;
      state.settings.maxIterations = Math.max(1, Number($("#cfg-max-iter").value || "5"));

      localStorage.setItem("rc_provider", state.settings.provider);
      localStorage.setItem("rc_model", state.settings.model);
      localStorage.setItem("rc_max_iter", String(state.settings.maxIterations));
      sessionStorage.setItem("rc_api_key", state.settings.apiKey);

      updateSettingsUI();
      $("#settings-modal-backdrop").classList.add("hidden");
      toast("Model settings saved.", "success");
    });
  }

  async function boot() {
    initTheme();
    bindEvents();
    try {
      const [cfg, samplesData] = await Promise.all([
        apiFetch("/api/config"),
        apiFetch("/api/samples"),
      ]);
      state.config = cfg;
      state.samples = samplesData.samples || [];
      if (!localStorage.getItem("rc_provider") && cfg.default_provider) {
        state.settings.provider = cfg.default_provider;
        state.settings.model = cfg.default_models[cfg.default_provider] || state.settings.model;
      }
      renderSamples();
    } catch (_) {}
    updateSettingsUI();
    await refreshSessionsDrawer();
    renderAll();
  }

  boot();
})();
