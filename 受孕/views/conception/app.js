/* 受孕 · WebUI 逻辑
   数据来自插件注册的 /<plugin>/state（经 dashboard bridge 代理）。
   endpoint 是"相对于插件"的后缀，前端会拼成
   /api/v1/plugins/extensions/{pluginName}/{endpoint}。 */

(() => {
  "use strict";

  let VIEW = null;
  let state = null;
  let busy = false;
  /* 本地预览用：把 window.__CONCEPTION_DEMO__ 设成一份 state 快照，
     不带面板打开这个页面也能看布局（不会真的操作）。 */
  const DEMO = window.__CONCEPTION_DEMO__ || null;

  const API_STATE = "web/state";
  const API_ACTION = "web/action";

  const PHASE_COLORS = {
    menstrual: "#f17a8a",
    follicular: "#7dd3fc",
    pre_ovulation: "#fbbf24",
    ovulation: "#fb923c",
    luteal: "#a78bfa",
    pms: "#f472b6",
    recovery: "#94a3b8",
    paused: "#64748b",
    unknown: "#94a3b8",
  };

  const KIND_CN = {
    pleasure: "快感",
    touch: "触碰",
    subzone: "子敏感度",
    orgasm: "高潮",
    ejaculation: "射精",
    roll: "判定",
    conception: "受孕",
    delivery: "生产",
    self_test: "验孕",
    pregnancy_test: "验孕",
    contraception: "避孕",
    expel: "排出",
    succubus: "魅魔",
    told: "告知",
    combo: "连续",
  };

  const $ = (id) => document.getElementById(id);

  /* AstrBot 把桥接脚本注入在 </body> 之前（也就是本文件之后），
     所以必须等它出现，不能一上来就断言"没有桥接"。 */
  async function waitForBridge(timeout = 2500) {
    const started = Date.now();
    for (;;) {
      const view = window.AstrBotPluginView || window.AstrBotPluginPage || null;
      if (view) return view;
      if (Date.now() - started >= timeout) return null;
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
  }

  function syncTheme(view) {
    if (!view || typeof view.onContext !== "function") return;
    view.onContext((ctx) => {
      if (ctx && typeof ctx.isDark === "boolean") {
        document.documentElement.setAttribute("data-theme", ctx.isDark ? "dark" : "light");
      }
    });
  }

  function fixed(value, digits = 1) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function pct(value, max) {
    const number = Number(value);
    const limit = Number(max) || 100;
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, (number / limit) * 100));
  }

  function setWidth(el, percent) {
    if (el) el.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }

  function badge(el, text, tone) {
    if (!el) return;
    el.textContent = text;
    el.dataset.tone = tone || "muted";
  }

  function timeText(ts) {
    const value = Number(ts);
    if (!value) return "—";
    const date = new Date(value * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  /* ---------------- 渲染 ---------------- */

  function render(payload) {
    state = payload;
    if (editor.open) {
      // 编辑页开着：只更新徽标，别把正在敲的字覆盖掉
      $("editorHint").textContent = editorHintText(payload);
      renderEditorNav();
      return;
    }
    renderHeader(payload);
    renderStatus(payload);
    renderNow(payload);
    renderProbability(payload);
    renderCycle(payload);
    renderPregnancy(payload);
    renderBody(payload);
    renderSuccubus(payload);
    renderTuning(payload);
    renderSizeHint(payload);
    renderZones(payload);
    renderSubZones(payload);
    renderMood(payload);
    renderToys(payload);
    renderAsmr(payload);
    renderSources(payload);
    renderLog(payload);
    $("footer").textContent = `受孕 v${payload.plugin?.version || "?"} · ${payload.state_path || ""}`;
  }

  function renderStatus(p) {
    const status = p.status || {};
    const main = status.main || { label: "平静", tone: "calm", note: "" };
    const mainEl = $("statusMain");
    mainEl.textContent = main.label || "平静";
    mainEl.dataset.tone = main.tone || "calm";
    $("statusNote").textContent = main.note || "";
    const chips = $("statusChips");
    chips.innerHTML = "";
    (status.chips || []).forEach((chip) => {
      const span = document.createElement("span");
      span.className = "status-chip";
      span.dataset.tone = chip.tone || "muted";
      span.textContent = chip.label || "";
      if (chip.note) span.title = chip.note;
      chips.appendChild(span);
    });
  }

  function renderHeader(p) {
    const gender = p.gender || {};
    const suitable = gender.suitable !== false;
    badge($("genderBadge"), suitable ? `人格：${genderLabel(gender.gender)}` : "人格：不适用",
      suitable ? "ok" : "bad");
    const gate = p.gate || {};
    badge($("gateBadge"), gate.ok ? "成人层：可用" : `成人层：${gate.reason || "未开"}`,
      gate.ok ? "ok" : "warn");
    const scene = p.scene || {};
    badge($("sceneBadge"), scene.active ? `场景中 ${scene.remaining ?? 0}′` : "场景：无",
      scene.active ? "ok" : "muted");

    const bits = [];
    if (p.pregnancy) bits.push(`孕期 ${p.pregnancy.month}/${p.pregnancy.months} 个月`);
    else if (p.postpartum?.active) {
      const stage = p.postpartum.stage;
      if (stage === "hard") bits.push("产后前段（绝对不受孕）");
      else if (stage === "low") bits.push("产后后段（概率很低）");
      else bits.push("产后恢复期");
    } else bits.push("未怀孕");
    if (p.combo?.overstimulated) bits.push("她刚过头，在难受");
    else if (p.scene?.active) bits.push("亲密场景进行中");
    $("subtitle").textContent = bits.join(" · ");
  }

  function genderLabel(gender) {
    return ({ female: "女", male: "男", other: "其他", unknown: "未知" })[gender] || "未知";
  }

  function renderNow(p) {
    const pleasure = p.pleasure || {};
    const value = Number(pleasure.value) || 0;
    const max = Number(pleasure.max) || 100;
    $("pleasureValue").textContent = fixed(value, 0);
    $("pleasureMax").textContent = fixed(max, 0);
    $("pleasureTier").textContent = pleasure.tier || "—";
    setWidth($("pleasureFill"), pct(value, max));

    const threshold = Number(pleasure.threshold) || 0;
    const mark = $("thresholdMark");
    mark.style.left = `${pct(threshold, max)}%`;
    mark.title = `高潮门槛 ${fixed(threshold, 0)}`;

    let hint = pleasure.tier_hint || "";
    if (!pleasure.post_orgasm && !p.combo?.overstimulated) {
      hint += `（高潮门槛 ${fixed(threshold, 0)}，快感到这条线才算真的到）`;
    }
    if (pleasure.post_orgasm) hint = "刚高潮过：身体敏感又发软，短暂不太想被碰。";
    if (p.combo?.overstimulated) hint = `刚过头了：碰一下都难受，还要缓 ${p.combo.rest} 分钟，她会想让你慢一点。`;
    $("pleasureHint").textContent = hint;

    const combo = p.combo || {};
    const count = Number(combo.count) || 0;
    const limit = Number(combo.limit) || 3;
    $("comboCount").textContent = count;
    $("comboLimit").textContent = limit;
    const dots = $("comboDots");
    dots.innerHTML = "";
    for (let index = 0; index < Math.max(limit, count); index += 1) {
      const dot = document.createElement("i");
      if (index < count) dot.className = index >= limit ? "over" : "on";
      dots.appendChild(dot);
    }
    $("comboHint").textContent = combo.overstimulated
      ? `已经过头，缓冲还剩 ${combo.rest} 分钟；再碰她会喊难受。`
      : count > 0
        ? `连续第 ${count} 次，再继续会更敏感；到 ${limit} 次再多就会过头。`
        : `12 分钟内再来算连续；连续到 ${limit} 次之后再多会过头。`;

    // 高潮忍耐条：满了再刺激一下就高潮
    const endure = p.endurance || {};
    if (endure.enabled) {
      const cap = Number(endure.cap) || 100;
      $("enduranceValue").textContent = fixed(endure.value, 0);
      $("enduranceCap").textContent = fixed(cap, 0);
      $("enduranceTier").textContent = endure.full ? "满了" : (endure.level_title || "还没");
      setWidth($("enduranceFill"), pct(endure.value, cap));
      $("enduranceFill").classList.toggle("is-full", !!endure.full);
      $("enduranceHint").textContent = endure.full
        ? "已经满了：再刺激一下就要到"
        : `快感到 ${fixed(endure.gain_at, 0)} 以上才攒得快（每次 +${fixed(endure.gain_high, 0)}，以下 +${fixed(endure.gain_low, 0)}）`
          + (endure.combo ? ` · 连续 ${endure.combo} 次后条变长到 ${fixed(cap, 0)}` : "");
    }

    renderSpecial(p);

    // 湿润度：快感条下面那条
    renderWetness(p);
  renderLewd(p);
  renderNightRaid(p);
  renderDesireStrategy(p);

    // 睡眠时段例外（含事后余韵）
    renderSwallow(p);
  renderUnbirth(p);
  renderSleepInside(p);
  renderSelfTest(p);
  renderChildren(p);
  renderClothing(p);
  renderBirth(p);
  renderCondom(p);
  renderWater(p);
  renderLube(p);
  renderUterusInsert(p);
  renderSleep(p);

    // 突然被弄
    renderSurprise(p);

    const orgasms = p.orgasms || {};
    const ejaculations = p.ejaculations || {};
    $("orgasmSession").textContent = orgasms.session ?? 0;
    $("orgasmToday").textContent = orgasms.today ?? 0;
    $("orgasmTotal").textContent = orgasms.total ?? 0;
    $("ejacTotal").textContent = ejaculations.total ?? 0;
    const uterus = p.uterus || {};
    $("uterusMl").textContent = fixed(uterus.ml, 1);
    $("uterusMax").textContent = fixed(uterus.capacity_effective ?? uterus.capacity, 0);
    $("uterusTier").textContent = uterus.level_title || uterus.tier_label || "空";
    if ($("uterusStretch")) {
      const stretched = Number(uterus.stretch) > 0;
      $("uterusStretch").hidden = !stretched;
      $("uterusStretch").textContent = stretched
        ? `撑开 +${fixed(uterus.stretch_percent, 0)}%` : "";
    }
    setWidth($("uterusFill"), pct(uterus.percent, 100));
    $("nowHint").textContent = (p.sleep && p.sleep.active)
      ? `睡眠时段·活动例外：已允许她发言（剩 ${p.sleep.minutes} 分钟）`
      : (p.gate?.ok ? "可以直接在这里推进" : "先授权成人层再操作");

    const testWindow = p.self_test?.window;
    const ready = !!(testWindow && testWindow.ready);
    $("testBadge").hidden = !ready;
    $("testBadge").dataset.tone = ready ? "warn" : "muted";
    const testButton = document.querySelector('[data-action="self_test"]');
    if (testButton) testButton.classList.toggle("pulse", ready);
  }

  function renderSizeHint(p) {
    const hint = $("sizeUterusHint");
    if (!hint) return;
    const s = (p && p.size) || {};
    const base = Number(s.uterus_length_base);
    const eff = Number(s.uterus_length_effective ?? s.uterus_length);
    if (eff > base + 0.05) {
      hint.hidden = false;
      hint.textContent = `当前实际子宫长度：${fixed(eff, 1)} cm（基础 ${fixed(base, 1)} cm，胎儿撑长 +${fixed(eff - base, 1)} cm）`;
    } else {
      hint.hidden = true;
      hint.textContent = "";
    }
  }

  function renderAsmr(p) {
    const info = (p && p.asmr) || null;
    if (!info || !$("asmrBlock")) return;
    const badge = $("asmrBadge");
    badge.textContent = !info.enabled ? "关" : info.active ? "助眠中" : "待机";
    badge.dataset.tone = info.active ? "ok" : (info.enabled ? "muted" : "warn");
    const mins = $("asmrMinutes");
    if (mins && document.activeElement !== mins) {
      mins.value = info.duration || 20;
    }
    const bits = [];
    if (info.active) {
      bits.push(`还剩 ${info.left_minutes} 分钟`);
      bits.push(`本次：耳朵 +${fixed(info.ear_gain, 2)} · 快感 +${fixed(info.pleasure_gain, 1)} · 忍耐 +${fixed(info.endurance_gain, 1)} · 羞耻 +${fixed(info.shame_gain, 1)}`);
      bits.push(`亲密 +${fixed(info.intimacy_gain, 1)} · 依恋 +${fixed(info.attachment_gain, 1)} · 睡眠压力提升 ${fixed(info.relief, 1)}`);
    } else if (info.asleep) {
      bits.push("她刚在助眠后睡着了");
    } else if (info.request_pending) {
      bits.push("她在等回应：要不要给她助眠");
    } else {
      bits.push(`助眠 ${info.duration || 20} 分钟起；捂耳 / 含耳日常也能用`);
    }
    $("asmrHint").textContent = bits.join(" · ");
    if ($("asmrKnownKeywords") && document.activeElement !== $("asmrKnownKeywords")) {
      $("asmrKnownKeywords").value = ((info.known_keywords || []).join(", "));
    }
    if ($("asmrEnabled")) {
      $("asmrEnabled").checked = !!info.enabled;
      $("asmrEnabledText").textContent = info.enabled ? "开" : "关";
      $("asmrRequestEnabled").checked = !!info.request_enabled;
      $("asmrRequestText").textContent = info.request_enabled ? "开" : "关";
    }
    $("btnAsmrStart").disabled = !info.enabled || info.active;
    $("btnAsmrExtend").disabled = !info.active;
    $("btnAsmrEnd").disabled = !info.active;
  }

  function openAsmrEditor() {
    document.body.classList.add("is-editing");
    $("asmrEditor").hidden = false;
    $("asmrEditor").classList.add("is-open");
  }

  function closeAsmrEditor() {
    $("asmrEditor").hidden = true;
    $("asmrEditor").classList.remove("is-open");
    document.body.classList.remove("is-editing");
    if (state) render(state);
  }

  function renderProbability(p) {
    const prob = p.probability;
    if (!prob) {
      const postpartum = p.postpartum || {};
      const blocked = !!(postpartum.active && postpartum.blocked);
      const score = document.querySelector(".prob-score");
      if (score) score.classList.add("is-empty");
      $("probValue").textContent = "—";
      $("probUnit").hidden = true;
      $("probTier").textContent = p.pregnancy ? "孕期中" : (blocked ? "产后前段" : "不可用");
      setWidth($("probFill"), 0);
      $("probNote").textContent = p.pregnancy
        ? "已经怀孕，不再判定受孕；等生产、周期恢复后才会重新掷骰。"
        : blocked
          ? `产后前 ${postpartum.hard_days || 14} 天（到 ${postpartum.hard_until || "—"}），这段时间绝对不受孕。`
          : "成人层未打开或人格不适用，暂时算不出概率。";
      $("probHint").textContent = p.pregnancy ? "孕期不判定" : (blocked ? "前段不判定" : "未就绪");
      $("factors").innerHTML = "";
      return;
    }
    $("probUnit").hidden = false;
    const score = document.querySelector(".prob-score");
    if (score) score.classList.remove("is-empty");
    $("probValue").textContent = fixed(prob.value, 1);
    $("probTier").textContent = prob.tier || "";
    const probMax = Number(prob.max) || 90;
    setWidth($("probFill"), pct(prob.value, probMax));
    $("probNote").textContent = `体外对照：${fixed(prob.outside, 2)}% · 上限 ${fixed(probMax, 0)}% · 这是"单次体内射精"的概率`
      + " · 肛内/深喉/体外不判定受孕"
      + (p.postpartum?.active && p.postpartum?.stage === "low"
        ? ` · 产后恢复期：概率 ×${fixed(p.postpartum.scale, 2)}`
        : "");
    $("probHint").textContent = prob.value >= 40 ? "这次很可能中" : "单次体内射精";

    const list = $("factors");
    list.innerHTML = "";
    (prob.factors || []).forEach((factor) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.className = "f-label";
      label.textContent = factor.label;

      const bar = document.createElement("span");
      bar.className = "f-bar";
      const fill = document.createElement("i");
      const isPercent = factor.kind === "percent";
      setWidth(fill, isPercent ? pct(factor.value, 40) : pct((Number(factor.value) - 1) * 100, 120));
      if (isPercent) fill.style.background = "linear-gradient(90deg, var(--amber), #f97316)";
      bar.appendChild(fill);

      const value = document.createElement("span");
      value.className = `f-value${isPercent ? " percent" : ""}`;
      value.textContent = isPercent ? `${fixed(factor.value, 1)}%` : `×${fixed(factor.value, 2)}`;
      li.append(label, bar, value);
      list.appendChild(li);
    });
  }

  function renderCycle(p) {
    const cycle = p.cycle || {};
    if ($("cyclePromptsOn")) {
      $("cyclePromptsOn").checked = cycle.prompts_enabled !== false;
      $("cyclePromptsText").textContent = cycle.prompts_enabled === false ? "关" : "开";
    }
    $("cyclePhase").textContent = cycle.label || "—";
    const menses = cycle.menstrual || {};
    if ($("cycleMenstrual")) {
      const show = menses.enabled !== false
        && (cycle.phase === "menstrual" || (menses.blood_ml || 0) > 0 || menses.pad_worn);
      $("cycleMenstrual").hidden = !show;
      if (show) {
        $("cycleBlood").textContent = `经血 ${menses.blood_ml || 0} ml / ${menses.capacity_ml || 0} ml`;
        const pad = menses.pad_worn
          ? `${menses.pad_label || "卫生巾"} ${menses.pad_percent || 0}%（${menses.pad_ml || 0}/${menses.pad_capacity_ml || 0} ml）`
          : "卫生巾：未穿";
        $("cyclePad").textContent = menses.pad_source ? `${pad}｜${menses.pad_source}` : pad;
        if ($("btnPadToyReinsert")) {
          $("btnPadToyReinsert").hidden = !(menses.changing && menses.toy_removed);
        }
        if ($("btnPadUbExit")) {
          $("btnPadUbExit").hidden = !(menses.changing && menses.unbirth_inside);
        }
        if ($("padShameCap") && document.activeElement !== $("padShameCap")) {
          $("padShameCap").value = menses.pad_shame_cap ?? 99;
        }
      }
    }
    $("cycleDay").textContent = cycle.day && cycle.total ? `第 ${cycle.day} / ${cycle.total} 天` : "—";
    const sourceLabel = {
      private_companion: "来源：private_companion",
      own: "来源：插件模拟周期",
      pregnancy: "来源：孕期暂停",
      postpartum: "来源：产后恢复",
      none: "来源：无数据",
    }[cycle.source] || "来源：—";
    $("cycleSource").textContent = sourceLabel;

    const strip = $("cycleStrip");
    strip.innerHTML = "";
    const phases = cycle.phases || [];
    const total = Number(cycle.total) || phases.reduce((sum, item) => sum + (Number(item.days) || 0), 0);
    if (phases.length && total > 0) {
      phases.forEach((item) => {
        const seg = document.createElement("i");
        seg.style.width = `${(Number(item.days) / total) * 100}%`;
        seg.style.background = PHASE_COLORS[item.phase] || PHASE_COLORS.unknown;
        seg.title = `${item.label} ${item.days} 天`;
        strip.appendChild(seg);
      });
      if (cycle.day) {
        const marker = document.createElement("span");
        marker.className = "today";
        marker.style.left = `${pct(Number(cycle.day) - 0.5, total)}%`;
        marker.title = `今天：${cycle.label}`;
        strip.appendChild(marker);
      }
    }

    const legend = $("cycleLegend");
    legend.innerHTML = "";
    (phases.length ? phases : [{ phase: "unknown", label: "未知", days: "-" }]).forEach((item) => {
      const span = document.createElement("span");
      const dot = document.createElement("em");
      dot.style.background = PHASE_COLORS[item.phase] || PHASE_COLORS.unknown;
      span.append(dot, document.createTextNode(`${item.label} ${item.days === "-" ? "" : item.days + "天"}`));
      legend.appendChild(span);
    });

    const noteBits = [];
    if (cycle.next_label) noteBits.push(`下一阶段：${cycle.next_label}`);
    if (cycle.source === "pregnancy") noteBits.push("孕期里周期整体暂停，PC 也不会再推经期");
    else noteBits.push("和 PC 的周期投影逐日一致（改 PC 面板这边跟着变）");
    $("cycleNote").textContent = noteBits.join(" · ");
  }

  function renderPregnancy(p) {
    const preg = p.pregnancy;
    const empty = $("pregEmpty");
    const body = $("pregBody");
    if (!preg) {
      empty.hidden = false;
      body.hidden = true;
      const postpartum = p.postpartum || {};
      if (postpartum.active) {
        const stage = postpartum.stage;
        let note = "";
        if (stage === "hard") note = `，前 ${postpartum.hard_days} 天不会受孕`;
        else if (stage === "low") note = `，后段概率 ×${fixed(postpartum.scale, 2)}`;
        $("pregHint").textContent = `产后恢复期（到 ${postpartum.until || "—"}${note}）`;
      } else {
        $("pregHint").textContent = "未怀孕";
      }
      return;
    }
    empty.hidden = true;
    body.hidden = false;
    $("pregHint").textContent = `第 ${preg.month} / ${preg.months} 个月`;
    $("pregMonth").textContent = preg.month;
    $("pregMonths").textContent = preg.months;
    $("pregStage").textContent = preg.stage || "";
    setWidth($("pregFill"), pct(preg.month, preg.months));
    $("pregWeek").textContent = `第 ${preg.week} 周`;
    $("pregDue").textContent = preg.due + (preg.due_jitter_days ? ` (${preg.due_jitter_days > 0 ? "+" : ""}${preg.due_jitter_days}天)` : "");
    $("pregLeft").textContent = `${preg.days_left} 天`;
    $("pregConceived").textContent = preg.conceived;

    const badges = $("pregBadges");
    badges.innerHTML = "";
    const items = [
      ["已知情", preg.known],
      ["只是怀疑", !preg.known && preg.suspected],
      ["已告诉他", preg.told],
      ["PC 周期已暂停", preg.suppressed],
      ["该验一验了", !!(p.self_test?.window && p.self_test.window.ready)],
      [preg.fetuses > 1 ? `${preg.fetuses} 胎` : "", preg.multiple],
    ];
    items.forEach(([label, on]) => {
      if (!on) return;
      const span = document.createElement("span");
      span.textContent = label;
      span.className = "on";
      badges.appendChild(span);
    });
    if (!badges.children.length) {
      const span = document.createElement("span");
      span.textContent = "她还不知道";
      badges.appendChild(span);
    }

    const notes = [];
    if (!preg.known && !preg.suspected) notes.push("她还没验过，提示词只写身体反应");
    if (preg.known && !preg.told) notes.push("她知道了，但还没告诉他——要不要说由她决定");
    if (preg.told) notes.push("她已经说开了");
    if (preg.stage_feel) notes.push(preg.stage_feel);
    if (preg.stage_intimacy) notes.push(preg.stage_intimacy);
    $("pregNote").textContent = notes.join(" · ");
  }

  function renderBody(p) {
    const hymen = p.hymen || {};
    const label = $("hymenLabel");
    if (label) {
      label.textContent = hymen.intact ? "完整" : "已破裂";
      label.dataset.tone = hymen.intact ? "on" : "off";
    }
    const note = $("hymenNote");
    if (note) {
      if (hymen.intact) {
        note.textContent = "第一次进入会疼、会破；未破裂也能怀孕/生产。";
      } else {
        const when = hymen.ruptured_at ? timeText(hymen.ruptured_at) : "";
        note.textContent = `已破裂${hymen.cause ? "（" + hymen.cause + "）" : ""}${when ? " · " + when : ""}`;
      }
    }
    if ($("hymenDamageFill")) {
      const damage = Number(hymen.damage) || 0;
      const top = Number(hymen.damage_max) || 100;
      setWidth($("hymenDamageFill"), top > 0 ? damage / top * 100 : 0);
    }
    if ($("hymenDamageText")) {
      const damage = Number(hymen.damage) || 0;
      const top = Number(hymen.damage_max) || 100;
      $("hymenDamageText").textContent = hymen.intact
        ? `损伤 ${fixed(damage, 0)} / ${fixed(top, 0)}（完全损伤会破裂）`
        : `已破裂（损伤 ${fixed(top, 0)} / ${fixed(top, 0)}）`;
    }
    if ($("btnHymenBlood")) {
      const on = hymen.blood_enabled !== false;
      $("btnHymenBlood").textContent = `处子血：${on ? "开" : "关"}`;
      $("btnHymenBlood").dataset.tone = on ? "on" : "off";
    }
    const u = p.uterus || {};
    if ($("uterusBodyMl")) $("uterusBodyMl").textContent = fixed(u.ml, 1);
    if ($("uterusBodyMax")) $("uterusBodyMax").textContent = fixed(u.capacity_effective ?? u.capacity, 0);
    if ($("uterusBodyTier")) $("uterusBodyTier").textContent = u.level_title || u.tier_label || "空";
    if ($("uterusOverflow")) $("uterusOverflow").checked = u.overflow_enabled !== false;
    if ($("uterusOverflowText")) {
      $("uterusOverflowText").textContent = `溢出：${u.overflow_enabled === false ? "关" : "开"}`;
    }
    if ($("uterusAfterLeak")) $("uterusAfterLeak").checked = u.after_leak_enabled !== false;
    if ($("uterusAfterLeakText")) {
      $("uterusAfterLeakText").textContent =
        `结束后漏出：${u.after_leak_enabled === false ? "关" : "开"}`;
    }
    if ($("uterusNote")) {
      const bits = [];
      bits.push(`装了 ${fixed(u.percent, 0)}%（${u.level_title || "空"}）`);
      if (Number(u.stretch) > 0) bits.push(`撑开 +${fixed(u.stretch_percent, 0)}%`);
      if (u.overflow_enabled === false) bits.push("不会溢（一直装）");
      else bits.push(`到 ${fixed(u.overflow_at, 0)}% 再射就会溢`);
      if (Number(u.overflow_last) > 0) bits.push(`上次溢出 ${fixed(u.overflow_last, 1)} ml`);
      if (u.after_leak_enabled !== false && Number(u.ml) > 0) {
        bits.push(`结束后 ${fixed(u.after_leak_per_hour, 0)} ml/小时漏到 ${fixed(u.after_leak_until, 0)}%`);
      }
      bits.push("怀孕时不会排（拒绝排胎儿）");
      $("uterusNote").textContent = bits.join(" · ");
    }
    const c = p.contraception || {};
    if ($("pillBlame")) {
      const enabled = (p.pill_blame || {}).enabled !== false;
      $("pillBlame").checked = enabled;
      $("pillBlameText").textContent = enabled ? "开" : "关";
      const once = (p.pill_blame || {}).once !== false;
      $("pillBlameOnce").checked = once;
      $("pillBlameOnceText").textContent = once ? "开" : "关";
    }
    if ($("pillCancelKeywords")) {
      const kw = p.contraception_keywords || {};
      $("pillCancelKeywords").value = (kw.pill_cancel_keywords || []).join(", ");
      $("pillTakeKeywords").value = (kw.pill_take_keywords || []).join(", ");
      $("pillPromiseKeywords").value =
        (kw.pill_inside_promise_keywords || []).join(", ");
    }
    if ($("pillProactive")) {
      const enabled = (p.pill_proactive || {}).enabled !== false;
      $("pillProactive").checked = enabled;
      $("pillProactiveText").textContent = enabled ? "开" : "关";
    }
    if ($("contraNote")) {
      const pill = c.pill_active ? `生效中（还剩 ${fixed(c.pill_hours_left, 1)} 小时）` : "没吃";
      $("contraNote").textContent =
        `药：${pill} · 套：${c.condom ? "戴着" : "没戴"} · 受孕倍率 ×${fixed(c.multiplier, 2)}`;
    }
  }

  function renderSuccubus(p) {
    const d = p.succubus || {};
    if ($("succBadge")) {
      $("succBadge").textContent = d.enabled ? "开" : "关";
      $("succBadge").dataset.tone = d.enabled ? "on" : "off";
    }
    if ($("succHint")) $("succHint").textContent = d.enabled ? "淫纹 / 榨取 / 怀孕意愿" : "在设置里开启";
    if ($("succLevel")) $("succLevel").textContent = `Lv.${d.level ?? 0}`;
    if ($("succUsed")) {
      $("succUsed").textContent = d.unlimited
        ? `不限（今日 ${d.used ?? 0}）`
        : `${d.used ?? 0} / ${d.daily_limit}`;
    }
    if ($("succDesire")) $("succDesire").textContent = `+${fixed(d.desire_gain, 1)} / 次`;
    if ($("succScale")) $("succScale").textContent = `×${fixed(d.gain_scale, 2)}`;
    if ($("succWilling")) {
      $("succWilling").textContent = d.willing === true ? "愿意" : d.willing === false ? "不愿意" : "未表态";
    }
    if ($("succTail")) {
      $("succTail").checked = d.tail_enabled === true;
    }
    if ($("succTailText")) {
      $("succTailText").textContent = d.tail_enabled
        ? (d.tail_active ? "开（魅魔尾巴）" : "开")
        : (d.tail_active ? "关（魅魔模式在，尾巴仍按魅魔算）" : "关");
    }
    if ($("succExpText")) {
      const need = Number(d.exp_need) || 100;
      const exp = Number(d.exp) || 0;
      const maxed = Number(d.level) >= Number(d.max_level || 5);
      $("succExpText").textContent = maxed ? "MAX" : `${exp} / ${need}`;
      setWidth($("succExpFill"), maxed ? 100 : pct(exp, need));
    }
    if ($("succNote")) {
      const parts = [];
      if (!d.enabled) parts.push("魅魔板块关着（配置 succubus.enabled）");
      if (d.conception_note) parts.push(d.conception_note);
      parts.push(`吸收 ×${fixed(d.absorption_multiplier, 0)}`);
      $("succNote").textContent = parts.join(" · ");
    }
  }

  function renderTuning(p) {
    const tune = p.tuning || {};
    document.querySelectorAll(".tune-input").forEach((input) => {
      if (document.activeElement === input) return;
      const section = tune[input.dataset.section] || {};
      const value = section[input.dataset.key];
      if (value !== undefined && value !== null) input.value = value;
    });
    document.querySelectorAll(".tune-input").forEach((input) => {
      const section = tune[input.dataset.section] || {};
      const manual = section.manual || {};
      input.classList.toggle("manual", manual[input.dataset.key] === true);
    });
  }

  /* 「忍耐设置 / 玩具设置」页：和配置默认分开，改的是 state 里的覆盖值 */
  function openTuneEditor(section) {
    if (!state || !state.tuning) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("tuneEditor").hidden = false;
    $("tuneEditor").classList.add("is-open");
    const toys = section === "toys";
    $("tuneEditorTitle").textContent = toys ? "玩具设置" : "忍耐条设置";
    $("tuneEditorHint").textContent = toys
      ? "日常小玩具能加多少快感/忍耐；改完立刻生效"
      : "快感涨得越多攒得越多；条满了再刺激一下就高潮";
    $("tuneEditorStatus").textContent = "已保存";
    $("tuneEditorStatus").dataset.tone = "ok";
    renderTuning(state);
    const enduranceBlock = $("ueEnduranceBlock");
    const toysBlock = $("ueToysBlock");
    if (enduranceBlock) enduranceBlock.hidden = toys;
    if (toysBlock) toysBlock.hidden = !toys;
    const endure = (state || {}).endurance || {};
    if ($("ueEnduranceNow")) {
      $("ueEnduranceNow").textContent = endure.enabled
        ? `现在 ${fixed(endure.value, 0)} / ${fixed(endure.cap, 0)}`
          + (endure.full ? "（满了）" : endure.combo ? `（连续 ${endure.combo} 次）` : "")
        : "（忍耐条关着）";
    }
    const block = $(toys ? "ueToysBlock" : "ueEnduranceBlock");
    if (block) block.scrollIntoView({ block: "start" });
    renderEndurancePrompts();
    const spot = (state || {}).special || {};
    if ($("teRotateTimer")) {
      $("teRotateTimer").checked = spot.rotate_on_timer !== false;
      $("teRotateTimerText").textContent = spot.rotate_on_timer !== false ? "开" : "关";
    }
  }

  function closeTuneEditor() {
    document.body.classList.remove("is-editing");
    $("tuneEditor").hidden = true;
    $("tuneEditor").classList.remove("is-open");
    if (state) render(state);
  }

  /* 忍耐条四段提示词的卡片 */
  function teCardHtml(item, max) {
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.level = String(item.level);
    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = item.title;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text te-text";
    area.dataset.level = String(item.level);
    area.maxLength = max;
    area.rows = 3;
    area.value = item.value || "";
    area.addEventListener("input", () => {
      count.textContent = `${area.value.length}/${max}`;
      $("tuneEditorStatus").textContent = "未保存…";
      $("tuneEditorStatus").dataset.tone = "warn";
    });

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.teResetField = String(item.level);
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  function renderEndurancePrompts() {
    const box = $("teEnduranceCards");
    if (!box) return;
    const groups = ((state || {}).endurance || {}).prompts || [];
    const group = groups[0] || { stages: [] };
    const max = promptData(state).max_len || 400;
    box.innerHTML = "";
    (group.stages || []).forEach((item) => box.appendChild(teCardHtml(item, max)));
  }

  async function saveEndurancePrompts() {
    const box = $("teEnduranceCards");
    if (!box) return;
    const texts = Array.from(box.querySelectorAll(".te-text")).map((el) => el.value);
    try {
      await editorPost({ action: "endurance_prompt_save", texts });
      toast("已保存");
      renderEndurancePrompts();
      $("tuneEditorStatus").textContent = "已保存";
      $("tuneEditorStatus").dataset.tone = "ok";
    } catch (error) {
      toast(`保存失败：${(error && error.message) || error}`);
    }
  }

  /* 湿润度：一直在变（不在活动里也算） */
  function renderWetness(p) {
    const data = p.wetness || {};
    if (!$("wetnessValue")) return;
    if (data.enabled === undefined) {
      $("wetnessValue").textContent = "—";
      $("wetnessTier").textContent = "—";
      $("wetnessFill").style.width = "0%";
      $("wetnessHint").textContent = "后端还是旧版本：重载「受孕」插件后湿润度才会出现";
      return;
    }
    if (!data.enabled) {
      $("wetnessValue").textContent = "—";
      $("wetnessTier").textContent = "关";
      $("wetnessFill").style.width = "0%";
      $("wetnessHint").textContent = "湿润度没开（配置 wetness.enabled）";
      return;
    }
    const value = Number(data.value) || 0;
    $("wetnessValue").textContent = fixed(value, 0);
    $("wetnessTier").textContent = data.level_title || "—";
    setWidth($("wetnessFill"), value);
    const notes = [];
    notes.push(`基础 ${fixed(data.base, 0)}`);
    if (data.base_float && data.base_float.enabled && data.base_float.amount > 0) {
      notes.push(`浮动 +${fixed(data.base_float.amount, 1)}（欲/快感/忍耐）`);
    }
    if (data.lube_bonus > 0) {
      notes.push(`润滑 +${fixed(data.lube_bonus, 0)}（夜袭不算）`);
    }
    if (data.prompt) notes.push(data.prompt);
    if (data.fish_available) {
      notes.push(`鱼之心欲 ${fixed(data.fish_desire, 0)}（涨得 ×${fixed(data.fish_gain_mult, 2)}）`);
    }
    $("wetnessHint").textContent = notes.join(" · ");
  }

  /* 「湿润度设置」页：基础/涨落 + 四段提示词 + 破处减痛 */
  function openLewdEditor() {
    document.body.classList.add("is-editing");
    $("lewdEditor").hidden = false;
    $("lewdEditor").classList.add("is-open");
    render(state);
  }

  function closeLewdEditor() {
    document.body.classList.remove("is-editing");
    $("lewdEditor").hidden = true;
    $("lewdEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openWetnessEditor() {
    if (!state || !state.wetness) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("wetnessEditor").hidden = false;
    $("wetnessEditor").classList.add("is-open");
    $("wetnessEditorStatus").textContent = "已保存";
    $("wetnessEditorStatus").dataset.tone = "ok";
    renderTuning(state);
    renderWetnessEditor();
  }

  function closeWetnessEditor() {
    document.body.classList.remove("is-editing");
    $("wetnessEditor").hidden = true;
    $("wetnessEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function weCardHtml(item, max) {
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.level = String(item.level);
    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = item.title;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text we-text";
    area.dataset.level = String(item.level);
    area.maxLength = max;
    area.rows = 3;
    area.value = item.value || "";
    area.addEventListener("input", () => {
      count.textContent = `${area.value.length}/${max}`;
      $("wetnessEditorStatus").textContent = "未保存…";
      $("wetnessEditorStatus").dataset.tone = "warn";
    });

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.weResetField = String(item.level);
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  function renderWetnessEditor() {
    const data = (state || {}).wetness || {};
    const box = $("weCards");
    if (box) {
      const max = promptData(state).max_len || 400;
      const group = (data.prompts || [])[0] || { stages: [] };
      box.innerHTML = "";
      (group.stages || []).forEach((item) => box.appendChild(weCardHtml(item, max)));
    }
    if ($("weNow")) {
      $("weNow").textContent = data.enabled
        ? `现在 ${fixed(data.value, 0)}/100（${data.level_title || "—"}）`
        : "（湿润度关着）";
    }
    if ($("weFishNow")) {
      $("weFishNow").textContent = data.fish_available
        ? `现在 ${fixed(data.fish_desire, 0)}，湿润度涨得 ×${fixed(data.fish_gain_mult, 2)}`
        : "（鱼之心没启用：不关联，湿润度照常走）";
    }
    if ($("weFishWrite")) {
      $("weFishWrite").checked = data.fish_write !== false;
      $("weFishWriteText").textContent = data.fish_write === false ? "关" : "开";
    }
    if ($("weBaseFloat")) {
      const float = data.base_float || {};
      $("weBaseFloat").checked = float.enabled !== false;
      $("weBaseFloatText").textContent = float.enabled === false
        ? "关" : `开（现在 +${fixed(float.amount, 1)}）`;
    }
  }

  async function saveWetnessPrompts() {
    const box = $("weCards");
    if (!box) return;
    const texts = Array.from(box.querySelectorAll(".we-text")).map((el) => el.value);
    try {
      await editorPost({ action: "wetness_prompt_save", texts });
      toast("已保存");
      $("wetnessEditorStatus").textContent = "已保存";
      $("wetnessEditorStatus").dataset.tone = "ok";
      renderWetnessEditor();
    } catch (error) {
      toast(`保存失败：${(error && error.message) || error}`);
    }
  }

  /* 睡眠时段：活动撞上睡觉时间时允许她发言（含事后余韵） */
  function renderSleep(p) {
    const data = p.sleep || {};
    if (!$("sleepBadge")) return;
    const inEvent = data.in_event === true;
    const active = data.active === true;
    let tone = "muted";
    let text = "未生效";
    if (active && inEvent) {
      tone = "ok";
      text = `活动期间 ${data.minutes} 分钟`;
    } else if (active && data.afterglow) {
      tone = "warn";
      text = `事后余韵 ${data.minutes} 分钟`;
    } else if (data.enabled === false) {
      text = "关";
    }
    badge($("sleepBadge"), text, tone);
    if ($("sleepNote")) {
      $("sleepNote").textContent = active
        ? (inEvent ? "她在睡觉，但活动里允许说话" : "活动刚结束，余韵里还允许说话")
        : "睡眠时段里活动时就允许她发言";
    }
    if ($("sleepAllow")) {
      $("sleepAllow").checked = data.enabled !== false;
      $("sleepAllowText").textContent = `允许发言：${data.enabled === false ? "关" : "开"}`;
    }
  }

  /* ---------------- 插入子宫 ---------------- */

  function openInsertEditor() {
    if (!state || !state.uterus_insert) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("insertEditor").hidden = false;
    $("insertEditor").classList.add("is-open");
  }

  function closeInsertEditor() {
    document.body.classList.remove("is-editing");
    $("insertEditor").hidden = true;
    $("insertEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openBirthEditor() {
    if (!state || !state.birth) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("birthEditor").hidden = false;
    $("birthEditor").classList.add("is-open");
    const info = state.birth || {};
    if ($("bsKeywords")) {
      $("bsKeywords").value = (info.keywords || []).join(", ");
    }
  }

  function closeBirthEditor() {
    document.body.classList.remove("is-editing");
    $("birthEditor").hidden = true;
    $("birthEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openZoneKeywordsEditor() {
    if (!state || !Array.isArray(state.zone_keywords)) {
      toast("后端还是旧版本：重载「受孕」插件后就能改");
      return;
    }
    document.body.classList.add("is-editing");
    $("zoneKeywordsEditor").hidden = false;
    $("zoneKeywordsEditor").classList.add("is-open");
    renderZoneKeywords();
  }

  function closeZoneKeywordsEditor() {
    document.body.classList.remove("is-editing");
    $("zoneKeywordsEditor").hidden = true;
    $("zoneKeywordsEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function renderZoneKeywords() {
    const box = $("zoneKeywordRows");
    if (!box) return;
    box.textContent = "";
    const rows = (state && state.zone_keywords) || [];
    rows.forEach((row) => {
      const card = document.createElement("section");
      card.className = "stage-card zone-keyword-block" + (row.custom ? " is-custom" : "");
      card.dataset.zone = row.key;

      const head = document.createElement("div");
      head.className = "stage-head";
      const title = document.createElement("b");
      title.textContent = row.label;
      head.appendChild(title);
      const badge = document.createElement("span");
      badge.className = "stage-badge" + (row.custom ? " is-custom" : "");
      badge.textContent = row.custom ? "自定义" : "内置默认";
      head.appendChild(badge);
      const count = document.createElement("span");
      count.className = "stage-count";
      head.appendChild(count);
      card.appendChild(head);

      const input = document.createElement("textarea");
      input.className = "stage-text";
      input.rows = 3;
      input.maxLength = 400;
      input.value = (row.value || []).join(", ");
      input.placeholder = "逗号分隔；留空 = 恢复默认";
      card.appendChild(input);

      const foot = document.createElement("div");
      foot.className = "stage-foot";
      const def = document.createElement("span");
      def.className = "stage-default";
      def.textContent = "默认：" + (row.default || []).join("、");
      foot.appendChild(def);
      const reset = document.createElement("button");
      reset.className = "link-btn";
      reset.type = "button";
      reset.dataset.zoneReset = row.key;
      reset.textContent = "恢复这段默认";
      foot.appendChild(reset);
      card.appendChild(foot);

      const updateCount = () => { count.textContent = `${[...input.value].length}/400`; };
      input.addEventListener("input", updateCount);
      updateCount();
      box.appendChild(card);
    });
  }

  async function saveAllZoneKeywords() {
    const texts = {};
    document.querySelectorAll("#zoneKeywordRows [data-zone]").forEach((card) => {
      const input = card.querySelector("textarea");
      if (input) texts[card.dataset.zone] = input.value;
    });
    const result = await sendAction("zone_keywords_save_all",
      { texts }).catch(() => null);
    if (result) toast(result);
    await load(false);
    renderZoneKeywords();
  }

  async function resetZoneKeywords(zone) {
    const result = await sendAction("zone_keywords_save", { zone, text: "" })
      .catch(() => null);
    if (result) toast(result);
    await load(false);
    renderZoneKeywords();
  }

  function openUnbirthEditor() {
    if (!state || !state.unbirth) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("unbirthEditor").hidden = false;
    $("unbirthEditor").classList.add("is-open");
  }

  function closeUnbirthEditor() {
    document.body.classList.remove("is-editing");
    $("unbirthEditor").hidden = true;
    $("unbirthEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openCondomEditor() {
    if (!state || !state.condom) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("condomEditor").hidden = false;
    $("condomEditor").classList.add("is-open");
  }

  function closeCondomEditor() {
    document.body.classList.remove("is-editing");
    $("condomEditor").hidden = true;
    $("condomEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openSquirtEditor() {
    if (!state || !state.squirt) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("squirtEditor").hidden = false;
    $("squirtEditor").classList.add("is-open");
  }

  function closeSquirtEditor() {
    document.body.classList.remove("is-editing");
    $("squirtEditor").hidden = true;
    $("squirtEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function openSwallowEditor() {
    if (!state || !state.swallow) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("swallowEditor").hidden = false;
    $("swallowEditor").classList.add("is-open");
    renderSwallowEditor();
  }

  function closeSwallowEditor() {
    document.body.classList.remove("is-editing");
    $("swallowEditor").hidden = true;
    $("swallowEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function renderSwallowEditor() {
    const data = (state && state.swallow) || {};
    if ($("swAuto")) {
      $("swAuto").checked = data.auto_enabled !== false;
      $("swAutoText").textContent = data.auto_enabled === false ? "关" : "开";
    }
  }

  function renderSwallow(p) {
    const info = (p && p.swallow) || null;
    const block = $("swallowBlock");
    if (!block) return;
    if (!info || info.enabled === false) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const badge = $("swallowBadge");
    badge.textContent = info.collected
      ? (info.mouth ? "在嘴里" : `已收集 ${info.collected}`)
      : "空";
    badge.dataset.tone = info.collected ? "ok" : "muted";
    $("swallowHint").textContent = info.collected
      ? "可以吞下去（加更多快感/欲望/湿润）"
      : `收集 +${info.pleasure}｜吞下 +${info.swallow_pleasure}`;
    $("btnSwSwallow").hidden = !info.collected;
  }

  function renderUnbirth(p) {
    const info = (p && p.unbirth) || null;
    const block = $("unbirthBlock");
    if (!block) return;
    if (info) {
      if ($("ubHeight") && document.activeElement !== $("ubHeight")) {
        $("ubHeight").value = info.height_cm;
      }
      if ($("ubWeight") && document.activeElement !== $("ubWeight")) {
        $("ubWeight").value = info.weight_kg;
      }
    }
    if (!info || info.enabled === undefined) {
      block.hidden = true;
      return;
    }
    if ($("ubRequest")) {
      $("ubRequest").checked = info.request_enabled !== false;
      $("ubRequestText").textContent = info.request_enabled === false ? "关" : "开";
    }
    block.hidden = false;
    const badge = $("unbirthBadge");
    if (info.enabled === false) {
      badge.textContent = "已关";
      badge.dataset.tone = "muted";
    } else {
      badge.textContent = info.inside ? "在里面" : (info.ratio < 0.99 ? "缩小中" : "原大小");
      badge.dataset.tone = info.inside ? "warn" : (info.ratio < 0.99 ? "ok" : "muted");
    }
    if ($("ubOn") && !$("ubOn").dataset.pending) {
      $("ubOn").checked = info.enabled !== false;
      $("ubOnText").textContent = info.enabled === false ? "关" : "开";
    }
    if (info.enabled === false) {
      if ($("ubResistWords") && document.activeElement !== $("ubResistWords")) {
      $("ubResistWords").value = (info.resist_keywords || []).join(", ");
    }
    $("unbirthHint").textContent = "Unbirth 关了，打开上面的开关才能用";
      ["btnUbShrink", "btnUbRestore", "btnUbEnter", "btnUbTube", "btnUbOvary", "btnUbExit", "btnUbBirth"].forEach((id) => {
        const el = $(id);
        if (el) el.hidden = true;
      });
      return;
    }
    $("unbirthHint").textContent =
      `比例 ${info.ratio}｜体积 ${Math.round(info.volume_ml)}ml / 上限 ${Math.round(info.limit_ml)}ml`
      + `｜最少缩到 ${info.min_ratio}${info.expansion_label ? "｜" + info.expansion_label : ""}`
      + (info.inside && info.pos ? `｜在：${info.pos}｜还要 ${info.remaining} 步` : "")
      + (info.gave_up ? "｜她刚放弃了，再试会重新开始" : "")
      + (info.can_enter || info.inside ? "" : "｜内裤没脱或还太大，进不去");
    if ($("ubPos")) {
      $("ubPos").hidden = !info.inside;
      $("ubPos").textContent = info.inside
        ? `${info.pos || "子宫"} · 还 ${info.remaining} 步` : "";
    }
    $("btnUbEnter").hidden = !!info.inside;
    $("btnUbTube").hidden = !!info.inside;
    $("btnUbOvary").hidden = !!info.inside;
    $("btnUbExit").hidden = !info.inside;
    $("btnUbBirth").hidden = !info.inside || info.can_birth === false;
    $("btnUbResist").hidden = !info.inside;
    $("btnUbShrink").hidden = !!info.inside;
    $("btnUbRestore").hidden = !!info.inside;
  }

  function renderSelfTest(p) {
    const info = (p && p.self_test) || {};
    const stick = $("selfTestStick");
    const label = $("selfTestResult");
    if (!stick || !label) return;
    const result = info.last_result || "";
    stick.dataset.result = result;
    label.textContent = result === "positive" ? "两条杠"
      : result === "weak" ? "一深一浅"
        : result === "negative" ? "一条杠" : "还没验";
    if ($("selfTestBy")) {
      $("selfTestBy").textContent = result
        ? (info.last_by === "self" ? "她自己验的" : "面板验的") : "";
    }
  }

  function renderChildren(p) {
    const data = (p && p.children) || {};
    const list = Array.isArray(data.list) ? data.list : [];
    if ($("childrenCount")) $("childrenCount").textContent = `${list.length} 个`;
    if ($("childrenEmpty")) $("childrenEmpty").hidden = list.length > 0;
    if ($("childrenList")) {
      $("childrenList").innerHTML = list.map((row) => {
        const name = row.name ? `${row.name} · ` : "";
        return `<div class="child-row"><b>${name}${row.sex}孩</b>`
          + `<span>${row.age_text || "—"} · ${row.care_label || "—"}</span></div>`;
      }).join("");
    }
    if ($("childCareMode") && document.activeElement !== $("childCareMode")) {
      $("childCareMode").value = data.care_mode || "family";
    }
    if ($("childInterrupt")) {
      $("childInterrupt").checked = data.interrupt_enabled !== false;
      $("childInterruptText").textContent = data.interrupt_enabled === false ? "关" : "开";
    }
  }

  function renderSleepInside(p) {
    const info = (p && p.sleep_inside) || null;
    const block = $("sleepInsideBlock");
    if (!block) return;
    if (!info || info.enabled === false) { block.hidden = true; return; }
    block.hidden = false;
    const badge = $("sleepInsideBadge");
    badge.textContent = info.active ? `在${info.place}` : (info.pending ? "等她答应" : "未开始");
    badge.dataset.tone = info.active ? "warn" : (info.pending ? "ok" : "muted");
    if ($("sleepInsideMode") && !info.active) {
      $("sleepInsideMode").value = info.pending || $("sleepInsideMode").value;
    }
    if (info.mode_hint && !info.active && $("sleepInsideMode")
        && document.activeElement !== $("sleepInsideMode")) {
      $("sleepInsideMode").value = info.mode_hint;
    }
    const kw = info.keywords || {};
    [["siKwVagina", "vagina"], ["siKwAnus", "anus"],
     ["siKwTail", "tail"], ["siKwUnbirth", "unbirth"]].forEach(([id, key]) => {
      if ($(id) && document.activeElement !== $(id)) {
        $(id).value = (kw[key] || []).join(", ");
      }
    });
    $("btnSleepInsideAsk").hidden = !!info.active;
    $("btnSleepInsideAccept").hidden = !!info.active || !info.pending;
    $("btnSleepInsideEnd").hidden = !info.active;
    $("btnSleepInsideSlight").hidden = !info.active;
    $("btnSleepInsideDeep").hidden = !info.active;
    $("sleepInsideHint").textContent = info.active
      ? `已经在${info.place}里睡着｜轻动 ${info.slight} 次｜抽插会弄醒`
      : (info.pending ? "她还没答应：点「她答应了」才开始" : "睡着后才能问；轻轻动不会弄醒，抽插会弄醒。");
  }

  function renderClothing(p) {
    const info = (p && p.clothing) || null;
    const block = $("clothingBlock");
    if (!block) return;
    if (!info || info.enabled === false) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const s = info.summary || {};
    $("clothingBadge").textContent = s.dress ? "连衣裙" : "已穿着";
    $("clothingBadge").dataset.tone = "ok";
    const wet = Array.isArray(info.wet) ? info.wet : [];
    const wetText = wet.length
      ? `｜${wet.map((row) => `${row.label}湿了（${row.cause_label}）`).join("、")}`
      : "";
    $("clothingHint").textContent =
      `上：${s.upper || "裸着"}｜下：${s.lower || "裸着"}｜腿：${s.legs || "裸着"}｜脚：${s.feet || "裸着"}`
      + `｜内衬：${s.under_top || "没穿"}｜内衣：${s.bra || "没穿"}、${s.underwear || "没穿"}${wetText}`;
    if ($("clothingEditor") && !$("clothingEditor").hidden) {
      renderClothingEditor();
    }
    if ($("sleepwearAsk")) {
      $("sleepwearAsk").hidden = !info.sleepwear_pending;
    }
  }

  function openPregnancyEditor() {
    document.body.classList.add("is-editing");
    $("pregnancyEditor").hidden = false;
    $("pregnancyEditor").classList.add("is-open");
    $("pregnancyEditorStatus").textContent = "设置";
    $("pregnancyEditorStatus").dataset.tone = "ok";
  }

  function closePregnancyEditor() {
    $("pregnancyEditor").hidden = true;
    $("pregnancyEditor").classList.remove("is-open");
    document.body.classList.remove("is-editing");
  }

  function openClothingEditor() {
    if (!state || !state.clothing) {
      toast("后端还是旧版本：重载「受孕」插件后就能换衣服");
      return;
    }
    document.body.classList.add("is-editing");
    $("clothingEditor").hidden = false;
    $("clothingEditor").classList.add("is-open");
    renderClothingEditor();
  }

  function closeClothingEditor() {
    document.body.classList.remove("is-editing");
    $("clothingEditor").hidden = true;
    $("clothingEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function renderClothingEditor() {
    const info = (state && state.clothing) || {};
    const box = $("clothingSlots");
    if (!box) return;
    box.innerHTML = "";
    (info.slots || []).forEach((slot) => {
      const pending = info.pending || {};
      const pendingSlots = Array.isArray(pending.slots) ? pending.slots : [];
      const pendingIndex = pendingSlots.indexOf(slot.slot);
      const pendingKey = pendingIndex >= 0 ? (pending.keys || [])[pendingIndex] : null;
      const card = document.createElement("section");
      card.className = `clothing-slot${pendingIndex >= 0 ? " is-pending" : ""}`;
      const head = document.createElement("div");
      head.className = "clothing-slot-head";
      const title = document.createElement("b");
      title.textContent = slot.label;
      const now = document.createElement("span");
      now.className = "muted";
      now.textContent = pendingIndex >= 0
        ? `换衣中：${pending.label || "换衣"}${pending.left_minutes ? `（约 ${pending.left_minutes} 分钟）` : "（马上完成）"}`
        : (slot.worn && slot.worn.label ? `现在：${slot.worn.label}` : "现在：没穿");
      head.append(title, now);
      if (slot.worn) {
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "link-btn clothing-refresh";
        refresh.textContent = "换件新的";
        refresh.dataset.slot = slot.slot;
        head.appendChild(refresh);
      }
      const items = document.createElement("div");
      items.className = "clothing-items";
      const bare = document.createElement("button");
      bare.type = "button";
      bare.className = `clothing-chip clothing-chip-bare${slot.worn ? "" : " is-worn"}${pendingIndex >= 0 && !pendingKey ? " is-pending" : ""}`;
      bare.textContent = "不穿";
      bare.dataset.slot = slot.slot;
      bare.dataset.key = "";
      bare.dataset.worn = slot.worn ? "1" : "";
      items.appendChild(bare);
      (slot.items || []).forEach((item) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `clothing-chip${slot.worn && slot.worn.key === item.key ? " is-worn" : ""}${pendingIndex >= 0 && pendingKey === item.key ? " is-pending" : ""}`;
        chip.textContent = item.label;
        chip.dataset.slot = slot.slot;
        chip.dataset.key = item.key;
        chip.dataset.worn = slot.worn && slot.worn.key === item.key ? "1" : "";
        items.appendChild(chip);
      });
      card.append(head, items);
      box.appendChild(card);
    });
  }

  async function outfitAction(slot, key, worn, immediate = false) {
    const body = worn ? { action: "outfit_remove", slot } : { action: "outfit_set", slot, key };
    if (immediate) body.immediate = true;
    const result = await editorPost(body).catch((error) => {
      toast(`换不了：${(error && error.message) || error}`);
      return null;
    });
    if (result) {
      const message = result.message || result.msg || result.data?.message;
      toast(message ? String(message) : "换好了");
    }
    await load(false);
    renderClothingEditor();
  }

  function renderBirth(p) {
    const info = (p && p.birth) || null;
    const block = $("birthBlock");
    if (!block) return;
    if (!info || info.enabled === false || !info.stage) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const badge = $("birthBadge");
    badge.textContent = info.label || "—";
    badge.dataset.tone = info.active ? "warn" : (info.stage === "done" ? "ok" : "muted");
    $("birthFill").style.width = `${Math.min(100, (Number(info.pain) || 0)
      / (Number(info.pain_max) || 100) * 100)}%`;
    $("birthHint").textContent = info.active
      ? `产痛 ${info.pain}/${info.pain_max}｜还剩约 ${info.left_minutes} 分钟｜安抚关键词：${(info.keywords || []).join("、")}`
      : info.stage === "due"
        ? `临产期：还有 ${info.days_left} 天到预产期`
        : info.stage === "done" ? "生产完成" : "—";
    $("btnBirthComfort").hidden = !info.active;
  }

  function renderCondom(p) {
    const info = (p && p.condom) || null;
    const block = $("condomBlock");
    if (!block) return;
    if (!info || info.enabled === false) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const badge = $("condomBadge");
    if (info.worn) {
      badge.textContent = "戴着";
      badge.dataset.tone = "ok";
    } else if (info.broken) {
      badge.textContent = "刚破了";
      badge.dataset.tone = "warn";
    } else {
      badge.textContent = "没戴";
      badge.dataset.tone = "muted";
    }
    $("condomHint").textContent = info.ask_pending
      ? "她拿着套，脸有点红，小声问要不要她帮忙戴"
      : `每次动作破裂 ${info.break_per_action}%｜她问帮戴 ${info.ask_chance}%`;
    $("btnCondomWear").hidden = !!info.worn;
    $("btnCondomRenew").hidden = false;
  }

  function renderWater(p) {
    const info = (p && p.squirt) || null;
    const block = $("waterBlock");
    if (!block) return;
    if (!info || info.enabled === false) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const value = Number(info.value) || 0;
    const max = Number(info.max) || 100;
    $("waterValue").textContent = value.toFixed(0);
    $("waterMax").textContent = max.toFixed(0);
    $("waterFill").style.width = `${Math.min(100, (value / max) * 100)}%`;
    $("waterTier").textContent = info.combo_recent ? `连续 ${info.count}` : "—";
    $("waterHint").textContent = value < (info.min_water || 0)
      ? "水不够，潮吹会喷不出来"
      : `每分钟回充 ${info.regen_per_minute}`;
  }

  function renderLube(p) {
    const info = (p && p.lube) || null;
    const badge = $("lubeBadge");
    if (!badge) return;
    if (info && info.active) {
      badge.hidden = false;
      badge.textContent = `润滑中 ${info.left_minutes} 分`;
    } else if (info && info.hand_active) {
      badge.hidden = false;
      badge.textContent = `手部润滑 ${info.hand_left_minutes} 分`;
    } else {
      badge.hidden = true;
    }
  }

  function renderUterusInsert(p) {
    const block = $("usBlock");
    if (!block) return;
    const info = (p && p.uterus_insert) || null;
    if (!info || typeof info !== "object") {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const badge = $("usBadge");
    if (info.active) {
      badge.textContent = "在里面";
      badge.dataset.tone = "ok";
    } else if (info.ready) {
      badge.textContent = "可以进";
      badge.dataset.tone = "ok";
    } else {
      badge.textContent = "还不够";
      badge.dataset.tone = "muted";
    }
    const req = info.requirements || {};
    $("usHint").textContent = info.active
      ? `痛感 ${info.pain}${info.force ? "（强行）" : ""}｜占用 ${info.capacity_ml} ml`
      : `湿润 ${req.wet}/${req.wet_at}｜快感 ${req.pleasure}/${req.pleasure_at}`;
    $("btnUsEnter").hidden = !!info.active;
    $("btnUsForce").hidden = !!info.active;
    $("btnUsExit").hidden = !info.active;
  }

  /* ---------------- 行为提示词（通用组） ---------------- */

  function behaviorGroups() {
    return (state && state.prompt_groups) || [];
  }

  function behaviorGroupNow() {
    const groups = behaviorGroups();
    const key = $("bpGroup") ? $("bpGroup").value : "";
    return groups.find((row) => row.key === key) || groups[0] || null;
  }

  let behaviorReturnTo = "";
  let keywordMode = "";

  function openKeywordEditor(mode) {
    if (mode !== "clothing" && mode !== "pill") return;
    keywordMode = mode;
    const isPill = mode === "pill";
    $("keywordTitle").textContent = isPill ? "避孕药关键词" : "衣装关键词";
    $("keywordHint").textContent = isPill
      ? "取消 / 确认 / 答应不内射，只填词，逗号分隔"
      : "脱下 / 穿上内裤，只填词，逗号分隔";
    $("kwClothingFields").hidden = isPill;
    $("kwPillFields").hidden = !isPill;
    if (isPill) {
      const kw = (state && state.contraception_keywords) || {};
      $("pillCancelKeywords").value = (kw.pill_cancel_keywords || []).join(", ");
      $("pillTakeKeywords").value = (kw.pill_take_keywords || []).join(", ");
      $("pillPromiseKeywords").value =
        (kw.pill_inside_promise_keywords || []).join(", ");
    } else {
      const kw = (state && state.clothing_keywords) || {};
      $("bpRemoveUnderwearWords").value =
        (kw.remove_underwear || []).join(", ");
      $("bpWearUnderwearWords").value =
        (kw.wear_underwear || []).join(", ");
    }
    $("keywordStatus").textContent = "关键词";
    $("keywordStatus").dataset.tone = "ok";
    $("behaviorEditor").hidden = true;
    $("behaviorEditor").classList.remove("is-open");
    $("keywordEditor").hidden = false;
    $("keywordEditor").classList.add("is-open");
    document.body.classList.add("is-editing");
  }

  function closeKeywordEditor() {
    $("keywordEditor").hidden = true;
    $("keywordEditor").classList.remove("is-open");
    $("behaviorEditor").hidden = false;
    $("behaviorEditor").classList.add("is-open");
    document.body.classList.add("is-editing");
  }

  async function saveKeywordEditor() {
    if (keywordMode === "pill") {
      const result = await sendAction("contraception_keywords_save", {
        pill_cancel_keywords: $("pillCancelKeywords").value,
        pill_take_keywords: $("pillTakeKeywords").value,
        pill_inside_promise_keywords: $("pillPromiseKeywords").value,
      }).catch(() => null);
      if (result) { toast(result); await load(false); }
      return;
    }
    const result = await sendAction("clothing_keywords_save", {
      remove: $("bpRemoveUnderwearWords").value,
      wear: $("bpWearUnderwearWords").value,
    }).catch(() => null);
    if (result) { toast(result); await load(false); }
  }

  function openBehaviorEditor(groupKey = "", returnTo = "") {
    if (!state || !state.prompt_groups) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    behaviorReturnTo = String(returnTo || "");
    if (behaviorReturnTo === "clothing") {
      $("clothingEditor").hidden = true;
      $("clothingEditor").classList.remove("is-open");
    } else if (behaviorReturnTo === "pregnancy") {
      $("pregnancyEditor").hidden = true;
      $("pregnancyEditor").classList.remove("is-open");
    } else if (behaviorReturnTo === "swallow") {
      $("swallowEditor").hidden = true;
      $("swallowEditor").classList.remove("is-open");
    } else if (behaviorReturnTo === "squirt") {
      $("squirtEditor").hidden = true;
      $("squirtEditor").classList.remove("is-open");
    } else if (behaviorReturnTo === "lewd") {
      $("lewdEditor").hidden = true;
      $("lewdEditor").classList.remove("is-open");
    }
    document.body.classList.add("is-editing");
    $("behaviorEditor").hidden = false;
    $("behaviorEditor").classList.add("is-open");
    $("behaviorStatus").textContent = "已保存";
    $("behaviorStatus").dataset.tone = "ok";
    renderBehaviorGroups();
    if (groupKey) $("bpGroup").value = groupKey;
    renderBehaviorCards();
  }

  function closeBehaviorEditor() {
    document.body.classList.remove("is-editing");
    $("behaviorEditor").hidden = true;
    $("behaviorEditor").classList.remove("is-open");
    if (behaviorReturnTo === "clothing") {
      behaviorReturnTo = "";
      $("clothingEditor").hidden = false;
      $("clothingEditor").classList.add("is-open");
      document.body.classList.add("is-editing");
      if (state) renderClothing(state);
      return;
    }
    if (behaviorReturnTo === "pregnancy") {
      behaviorReturnTo = "";
      $("pregnancyEditor").hidden = false;
      $("pregnancyEditor").classList.add("is-open");
      document.body.classList.add("is-editing");
      return;
    }
    if (behaviorReturnTo === "swallow") {
      behaviorReturnTo = "";
      $("swallowEditor").hidden = false;
      $("swallowEditor").classList.add("is-open");
      document.body.classList.add("is-editing");
      return;
    }
    if (behaviorReturnTo === "squirt" || behaviorReturnTo === "lewd") {
      const key = behaviorReturnTo === "squirt" ? "squirtEditor" : "lewdEditor";
      behaviorReturnTo = "";
      $(key).hidden = false;
      $(key).classList.add("is-open");
      document.body.classList.add("is-editing");
      return;
    }
    behaviorReturnTo = "";
    if (state) render(state);
  }

  function renderBehaviorGroups() {
    const select = $("bpGroup");
    if (!select) return;
    const groups = behaviorGroups();
    const keep = select.value;
    select.innerHTML = "";
    groups.forEach((row) => {
      const option = document.createElement("option");
      option.value = row.key;
      option.textContent = `${row.label}${row.custom_count ? `（已改 ${row.custom_count}）` : ""}`;
      select.appendChild(option);
    });
    if (keep && groups.some((row) => row.key === keep)) select.value = keep;
  }

  function bpCardHtml(item, max) {
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.key = item.key;
    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = item.label;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text bp-text";
    area.dataset.key = item.key;
    area.maxLength = max;
    area.rows = 3;
    area.value = item.value || "";
    area.addEventListener("input", () => {
      count.textContent = `${area.value.length}/${max}`;
      $("behaviorStatus").textContent = "未保存…";
      $("behaviorStatus").dataset.tone = "warn";
    });

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.bpReset = item.key;
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  function renderBehaviorCards() {
    const group = behaviorGroupNow();
    const box = $("bpCards");
    if (!box) return;
    box.innerHTML = "";
    if (!group) {
      $("bpGroupNote").textContent = "—";
      return;
    }
    $("bpGroupNote").textContent = `${group.items.length} 段 · ${group.custom_count ? `已改 ${group.custom_count}` : "全默认"}`;
    if ($("btnBehaviorKeywords")) {
      const hasKeywords = group.key === "clothing" || group.key === "pill";
      $("btnBehaviorKeywords").hidden = !hasKeywords;
      $("btnBehaviorKeywords").dataset.group = hasKeywords ? group.key : "";
    }
    group.items.forEach((item) => box.appendChild(bpCardHtml(item, group.max_len || 400)));
  }

  async function saveBehaviorGroup() {
    const group = behaviorGroupNow();
    if (!group) return;
    const box = $("bpCards");
    const texts = {};
    box.querySelectorAll(".bp-text").forEach((area) => {
      texts[area.dataset.key] = area.value;
    });
    try {
      await editorPost({ action: "behavior_prompt_save", group: group.key, texts });
      toast("已保存");
      $("behaviorStatus").textContent = "已保存";
      $("behaviorStatus").dataset.tone = "ok";
      await load(false);
      renderBehaviorGroups();
      renderBehaviorCards();
    } catch (error) {
      toast(`保存失败：${(error && error.message) || error}`);
    }
  }

  /* 突然被弄：不在活动里点按钮时她会被吓一跳 */
  function renderSurprise(p) {
    const data = p.surprise || {};
    if (!$("surpriseBadge")) return;
    if (data.enabled === false) {
      badge($("surpriseBadge"), "关", "muted");
      $("surpriseNote").textContent = "不开的话点按钮就没什么反应";
      $("surpriseOn").checked = false;
      $("surpriseOnText").textContent = "反应：关";
      return;
    }
    if (!data.active) {
      badge($("surpriseBadge"), "未生效", "muted");
      $("surpriseNote").textContent = "不在活动里点按钮，她会吓一跳";
    } else if (data.stage === "shock") {
      badge($("surpriseBadge"), `还没缓过来 ${data.left_minutes} 分钟`, "warn");
      $("surpriseNote").textContent = `刚才被突然弄了一下（${data.label || "碰"}）`
        + (data.sent ? "· 已经主动发了消息" : (data.proactive ? "· 可能会主动发消息" : ""));
    } else {
      badge($("surpriseBadge"), `反应过来了 ${data.left_minutes} 分钟`, "ok");
      $("surpriseNote").textContent = `她已经反应过来（${data.label || "碰"}）：正害羞`;
    }
    if ($("surpriseOn")) {
      $("surpriseOn").checked = data.enabled !== false;
      $("surpriseOnText").textContent = `反应：${data.enabled === false ? "关" : "开"}`;
    }
  }

  /* 「突然被弄」设置页 */
  function openSurpriseEditor() {
    if (!state || !state.surprise) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("surpriseEditor").hidden = false;
    $("surpriseEditor").classList.add("is-open");
    $("surpriseEditorStatus").textContent = "已保存";
    $("surpriseEditorStatus").dataset.tone = "ok";
    renderTuning(state);
    renderSurpriseEditor();
  }

  function closeSurpriseEditor() {
    document.body.classList.remove("is-editing");
    $("surpriseEditor").hidden = true;
    $("surpriseEditor").classList.remove("is-open");
    $("behaviorEditor").hidden = true;
    $("behaviorEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function seCardHtml(item, max) {
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.stage = item.key;
    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = item.title;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text se-text";
    area.dataset.stage = item.key;
    area.maxLength = max;
    area.rows = 4;
    area.value = item.value || "";
    area.addEventListener("input", () => {
      count.textContent = `${area.value.length}/${max}`;
      $("surpriseEditorStatus").textContent = "未保存…";
      $("surpriseEditorStatus").dataset.tone = "warn";
    });

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.seResetField = item.key;
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  function renderSurpriseEditor() {
    const data = (state || {}).surprise || {};
    if (!$("seCards")) return;
    const groups = data.prompts || [];
    const group = groups[0] || { stages: [] };
    const max = group.max_len || 400;
    const box = $("seCards");
    box.innerHTML = "";
    (group.stages || []).forEach((item) => box.appendChild(seCardHtml(item, max)));
    if ($("seMessage") && document.activeElement !== $("seMessage")) {
      $("seMessage").value = data.message_custom ? (data.message || "") : "";
    }
    if ($("surpriseNow")) {
      $("surpriseNow").textContent = data.enabled === false
        ? "（关着）"
        : (data.active
          ? (data.stage === "shock" ? "她还没缓过来" : "她已经反应过来了")
          : `现在没触发（概率 ${fixed(data.chance, 0)}%）`);
    }
  }

  async function saveSurprisePrompts() {
    const box = $("seCards");
    if (!box) return;
    const areas = Array.from(box.querySelectorAll(".se-text"));
    try {
      for (const area of areas) {
        await editorPost({ action: "surprise_prompt_save",
                           stage: area.dataset.stage, text: area.value });
      }
      toast("已保存");
      $("surpriseEditorStatus").textContent = "已保存";
      $("surpriseEditorStatus").dataset.tone = "ok";
      renderSurpriseEditor();
    } catch (error) {
      toast(`保存失败：${(error && error.message) || error}`);
    }
  }

  /* 特别敏感点：活动里她这会儿最敏感的地方 + 玩具特别档位 */
  function renderSpecial(p) {
    const data = p.special || {};
    if (!$("specialBadge")) return;
    if (!data.enabled) {
      badge($("specialBadge"), "关", "off");
      $("specialZone").textContent = "—";
      $("specialLeft").textContent = "";
      $("specialNote").textContent = "特别敏感点没开（配置 special.enabled）";
      return;
    }
    badge($("specialBadge"), "活动里", "ok");
    $("specialZone").textContent = data.label || "—";
    $("specialLeft").textContent = data.rotate_on_timer === false
      ? "（到点不自动换，碰过才换）"
      : (data.remaining ? `约 ${data.remaining} 分钟后会换` : "");
    const bonus = [];
    if (Number(data.pleasure_bonus) > 0) bonus.push(`快感 +${fixed(data.pleasure_bonus, 0)}`);
    if (Number(data.endurance_bonus) > 0) bonus.push(`忍耐 +${fixed(data.endurance_bonus, 0)}`);
    $("specialNote").textContent = bonus.length
      ? `碰到这里多涨：${bonus.join("、")}`
      : "碰到这里没有额外加成（数值可在忍耐设置里调）";

    // 玩具特别档位：显示现在轮到哪个小玩具
    const toy = data.toy || {};
    if ($("specialToy")) {
      if (!toy.enabled || !toy.key) {
        $("specialToy").textContent = toy.enabled === false ? "—" : "（没有可用玩具）";
        $("specialToyLeft").textContent = "";
        $("specialToyNote").textContent = "";
      } else {
        $("specialToy").textContent = toy.label || toy.key;
        $("specialToyLeft").textContent = toy.timed === false
          ? "（到点不换，用到了才换）"
          : (toy.remaining ? `约 ${toy.remaining} 分钟后会换` : "");
        const parts = [];
        if (Number(data.daily_pleasure) > 0) parts.push(`快感 +${fixed(data.daily_pleasure, 0)}`);
        if (Number(data.daily_endurance) > 0) parts.push(`忍耐 +${fixed(data.daily_endurance, 0)}`);
        $("specialToyNote").textContent = parts.length
          ? `日常用这个玩具会多涨：${parts.join("、")}（概率 ${fixed(data.daily_chance, 0)}%）`
          : "日常用这个玩具没有额外加成（数值可在忍耐设置里调）";
      }
    }
  }

  function renderZones(p) {
    const list = $("zoneList");
    const rows = p.zones || [];
    const edge = p.edge || {};
    const input = $("edgeStepInput");
    if (input && document.activeElement !== input) {
      const value = Number(edge.step);
      input.value = Number.isFinite(value) ? value : 8;
    }
    $("edgeStepHint").textContent = edge.enabled
      ? `下一次实际 +${fixed(edge.next_bonus, 1)}（之后每次 ×${fixed(edge.decay, 2)}）`
      : "寸止已关闭";
    list.innerHTML = "";
    $("zoneEmpty").hidden = rows.length > 0;
    if (!rows.length) {
      $("zoneHint").textContent = "敏感点系统关着";
      return;
    }
    $("zoneHint").textContent = "开发度 / 敏感度 / 每次涨幅";
    rows.forEach((row) => {
      const li = document.createElement("li");
      li.className = `zone-row${row.enabled ? "" : " is-off"}`;

      const name = document.createElement("span");
      name.className = "z-name";
      if (row.key === "tail") {
        const label = document.createElement("label");
        label.className = "mini-switch z-tail-switch";
        label.title = "角色没有尾巴就关掉";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!row.enabled;
        input.dataset.zone = "tail";
        const word = document.createElement("span");
        word.textContent = row.label;
        label.append(input, word);
        name.appendChild(label);
      } else {
        name.textContent = row.label;
      }

      const devStep = document.createElement("span");
      devStep.className = "z-dev-step";
      if (row.enabled) {
        const devMinus = document.createElement("button");
        devMinus.type = "button";
        devMinus.className = "z-btn";
        devMinus.dataset.action = "zone_dev";
        devMinus.dataset.zone = row.key;
        devMinus.dataset.delta = "-1";
        devMinus.title = "开发度 −1";
        devMinus.textContent = "−";

        const devInput = document.createElement("input");
        devInput.type = "number";
        devInput.className = "z-dev-input";
        devInput.min = "0";
        devInput.max = "100";
        devInput.step = "1";
        devInput.value = row.dev;
        devInput.dataset.zone = row.key;
        devInput.title = (row.dev_manual
          ? `手动开发度（配置值 ${row.dev_config}%，点 ↺ 恢复）`
          : "直接输入 0–100 改开发度")
          + (row.dev_bonus ? `；其中子敏感度溢出加了 ${fixed(row.dev_bonus, 1)} 点` : "");
        if (row.dev_manual) devInput.classList.add("manual");

        const devPlus = document.createElement("button");
        devPlus.type = "button";
        devPlus.className = "z-btn";
        devPlus.dataset.action = "zone_dev";
        devPlus.dataset.zone = row.key;
        devPlus.dataset.delta = "1";
        devPlus.title = "开发度 +1";
        devPlus.textContent = "＋";

        const devReset = document.createElement("button");
        devReset.type = "button";
        devReset.className = "z-btn z-reset";
        devReset.dataset.action = "zone_dev";
        devReset.dataset.zone = row.key;
        devReset.dataset.reset = "1";
        devReset.title = "恢复配置的开发度";
        devReset.textContent = "↺";
        devReset.hidden = !row.dev_manual;

        const percent = document.createElement("span");
        percent.className = "z-pct";
        percent.textContent = "%";

        devStep.append(devMinus, devInput, percent, devPlus, devReset);
      } else {
        devStep.textContent = "—";
      }

      const bar = document.createElement("span");
      bar.className = "z-bar";
      const fill = document.createElement("i");
      setWidth(fill, row.enabled ? row.dev : 0);
      bar.appendChild(fill);

      const meta = document.createElement("span");
      meta.className = "z-meta";
      meta.textContent = `敏感 ×${fixed(row.sensitivity, 2)}`;
      if (row.sens_bonus) {
        meta.classList.add("has-bonus");
        meta.title = `子敏感度溢出攒的加成：敏感度 +${fixed(row.sens_bonus, 2)}`
          + `（配置值 ×${fixed(row.base_sensitivity, 2)}）`
          + (row.dev_bonus ? `、开发度 +${fixed(row.dev_bonus, 1)}` : "");
      }

      const step = document.createElement("span");
      step.className = "z-step";
      if (row.enabled) {
        const minus = document.createElement("button");
        minus.type = "button";
        minus.className = "z-btn";
        minus.dataset.action = "zone_gain";
        minus.dataset.zone = row.key;
        minus.dataset.delta = "-0.5";
        minus.title = "每次涨幅 −0.5";
        minus.textContent = "−";

        const gainInput = document.createElement("input");
        gainInput.type = "number";
        gainInput.className = "z-input";
        gainInput.min = "0";
        gainInput.max = "50";
        gainInput.step = "0.5";
        gainInput.value = fixed(row.gain, 1);
        gainInput.dataset.zone = row.key;
        gainInput.title = row.manual
          ? `手动值（公式值 +${fixed(row.formula_gain, 1)}，点 ↺ 恢复）`
          : "直接输入数字可改每次涨幅";
        if (row.manual) gainInput.classList.add("manual");

        const plus = document.createElement("button");
        plus.type = "button";
        plus.className = "z-btn";
        plus.dataset.action = "zone_gain";
        plus.dataset.zone = row.key;
        plus.dataset.delta = "0.5";
        plus.title = "每次涨幅 +0.5";
        plus.textContent = "＋";

        const reset = document.createElement("button");
        reset.type = "button";
        reset.className = "z-btn z-reset";
        reset.dataset.action = "zone_gain";
        reset.dataset.zone = row.key;
        reset.dataset.reset = "1";
        reset.title = "恢复按公式计算";
        reset.textContent = "↺";
        reset.hidden = !row.manual;

        step.append(minus, gainInput, plus, reset);
      } else {
        step.textContent = "—";
      }

      const touch = document.createElement("button");
      touch.type = "button";
      touch.className = "z-touch";
      touch.dataset.action = "touch";
      touch.dataset.zone = row.key;
      touch.title = `${row.label}：碰一次（快感 +${fixed(row.gain, 1)}）`;
      touch.textContent = "碰";
      touch.disabled = !row.enabled;

      li.append(name, devStep, bar, meta, step, touch);
      list.appendChild(li);
    });
  }




  /* 子敏感度：只在受孕活动（亲密场景）里生效的第二层条。
     三段（初起 / 发烫 / 将溢）各有提示词；条满了溢出一把，然后几秒内退回 0。 */
  let fallGen = 0;

  function renderSubZones(p) {
    const sub = p.sub_zones;
    if (!sub) {
      // 后端还没重载（旧版本没有这个接口）：先把话说清楚，别画一个空卡片
      badge($("subBadge"), "待重载", "warn");
      $("subHint").textContent = "后端还是旧版本";
      $("subZoneList").innerHTML = "";
      $("subZoneEmpty").hidden = true;
      $("subZoneNote").textContent =
        "在 AstrBot 面板里重载「受孕」插件（或重启）后刷新本页，这个板块才会读到数据。";
      return;
    }
    const rows = sub.rows || [];
    const list = $("subZoneList");
    const daily = p.daily || {};
    const inScene = !!sub.scene;
    const dailyOnly = !!daily.active && !(p.scene && p.scene.active);
    const live = !!sub.enabled && (inScene || !sub.scene_only);
    badge($("subBadge"), !sub.enabled ? "关" : dailyOnly ? "日常中" : live ? "活动中" : "不在活动",
      !sub.enabled ? "off" : dailyOnly ? "warn" : live ? "on" : "muted");
    const first = rows.find((row) => row.gain) || {};
    $("subHint").textContent = !sub.enabled
      ? "配置 sub_zones.enabled 关着"
      : dailyOnly
        ? `日常小场景：玩具只推高${daily.zone_label || "对应部位"}，别写正式亲密`
        : live
          ? `碰一下 +${fixed(first.gain, 0)} 左右，两三下就满`
          : "不在受孕活动里：进度会很快退回 0（碰她一下就算开场）";

    list.innerHTML = "";
    $("subZoneEmpty").hidden = rows.length > 0;

    const note = [];
    note.push(`满条：开发度 +${fixed(sub.burst_dev, 0)} · 敏感度 +${fixed(sub.burst_sensitivity, 2)}`
      + ` · 快感 +${fixed(sub.burst_pleasure, 0)}`);
    note.push(`${fixed(sub.fall_seconds, 1)} 秒内退回 0`);
    if (sub.total_bursts) note.push(`已溢出 ${sub.total_bursts} 次`);
    if (!live) note.push("碰她一下就会开场");
    $("subZoneNote").textContent = note.join(" · ");

    rows.forEach((row) => {
      const isDailyZone = dailyOnly && row.key === daily.zone;
      const li = document.createElement("li");
      li.className = `subzone-row${row.charge > 0 ? "" : " is-empty"}`
        + `${row.falling ? " is-burst" : ""}${isDailyZone ? " is-daily" : ""}`;
      li.dataset.key = row.key;
      li.dataset.level = String(row.level || 0);

      const head = document.createElement("div");
      head.className = "s-head";

      const name = document.createElement("span");
      name.className = "s-name";
      name.textContent = row.label;

      const meter = document.createElement("span");
      meter.className = "s-meter";
      const fill = document.createElement("i");
      setWidth(fill, row.percent || 0);
      meter.appendChild(fill);

      const level = document.createElement("span");
      level.className = `s-level${row.level ? "" : " is-idle"}`;
      level.textContent = row.level ? row.level_title : "未起";
      level.title = `${row.level_title}：${row.prompt}`;

      const methodTag = document.createElement("span");
      methodTag.className = `s-method${row.method_label ? " is-on" : ""}`;
      methodTag.textContent = row.method_label || "—";
      methodTag.title = row.method_label
        ? `这个部位正在被怎么弄：${row.method_label}`
        : (row.methods && row.methods.length
          ? `可选方式：${row.methods.map((item) => item.label).join(" / ")}`
          : "这个部位没有方式");

      const fillBtn = document.createElement("button");
      fillBtn.type = "button";
      fillBtn.className = "s-btn";
      fillBtn.dataset.action = "sub_zone_fill";
      fillBtn.dataset.zone = row.key;
      fillBtn.textContent = "满";
      fillBtn.title = live ? "直接填满并溢出一次（看提示词和奖励）" : "要先进受孕活动";
      fillBtn.disabled = !live;

      const resetBtn = document.createElement("button");
      resetBtn.type = "button";
      resetBtn.className = "s-btn s-reset";
      resetBtn.dataset.action = "sub_zone_reset";
      resetBtn.dataset.zone = row.key;
      resetBtn.textContent = "↺";
      resetBtn.title = "这个部位清零";
      resetBtn.disabled = !row.charge && !row.falling;

      head.append(name, meter, methodTag, level, fillBtn, resetBtn);

      li.appendChild(head);
      if (row.level > 0 || row.charge > 0) {
        const prompt = document.createElement("p");
        prompt.className = "s-prompt";
        prompt.textContent = row.prompt || "—";
        prompt.title = (row.level_prompts || []).join(" / ") || row.prompt || "";
        li.appendChild(prompt);
      }
      list.appendChild(li);
    });

    animateFalls(p, sub);
  }

  /* 溢出后的"快速回落"在本地按时间补动画，不用等下一次刷新：
     条从满退回 0 的同时，段位和提示词也跟着一段一段往回退。 */
  function animateFalls(p, sub) {
    fallGen += 1;
    const gen = fallGen;
    const fall = Number(sub.fall_seconds) || 0;
    if (!sub.enabled || fall <= 0) return;
    const offset = (Number(p.server_time) || Date.now() / 1000) - Date.now() / 1000;
    (sub.rows || []).forEach((row) => {
      if (!row.falling || !row.burst_at) return;
      const li = document.querySelector(`.subzone-row[data-key="${row.key}"]`);
      const fill = li ? li.querySelector(".s-meter i") : null;
      if (!fill) return;
      const chip = li.querySelector(".s-level");
      const prompt = li.querySelector(".s-prompt");
      const titles = row.level_titles || [];
      const prompts = row.level_prompts || [];
      fill.style.transition = "none";
      const step = () => {
        if (gen !== fallGen) return;
        const serverNow = Date.now() / 1000 + offset;
        const left = Math.max(0, 1 - (serverNow - row.burst_at) / fall);
        setWidth(fill, left * 100);
        const level = left <= 0 ? 0 : Math.min(3, Math.ceil(left * 3 - 1e-6));
        li.dataset.level = String(level);
        if (chip) {
          chip.textContent = level ? (titles[level - 1] || "") : "未起";
          chip.classList.toggle("is-idle", !level);
        }
        if (prompt) {
          prompt.textContent = level ? (prompts[level - 1] || "") : (row.idle_prompt || "");
          li.classList.toggle("is-empty", !level);
        }
        if (left > 0) {
          requestAnimationFrame(step);
        } else {
          li.classList.remove("is-burst");
          fill.style.transition = "";
        }
      };
      requestAnimationFrame(step);
    });
  }

  /* ---------------- 敏感点阶段性表现（新页面：改三段提示词） ---------------- */

  const editor = {
    open: false,
    zone: "",
    tab: "stage",
    dirty: false,
    saving: false,
    timer: null,
    // 还没确认写进服务端的草稿：{ "zone:tab": [每段的文字] }。
    // 服务端慢的时候切走再切回来，也还是你刚敲的字，而不是旧的。
    drafts: {},
    saveSeq: 0,
    pending: 0,
  };

  function editorKey(zone = editor.zone, tab = editor.tab) {
    return `${zone}:${tab}`;
  }

  const MOOD_PREFIX = "mood:";

  function promptData(p) {
    return (p && p.sub_prompts) || { zones: [], custom_total: 0, max_len: 400 };
  }

  /* 设置页左边列表里的「伪部位」：日常情绪两条（子宫充盈/溢出挪到「子宫设置」页了） */
  function extraZones(p) {
    const groups = [];
    (((p || {}).mood_prompts) || []).forEach((item) => groups.push({
      key: `mood:${item.key}`,
      raw: item.key,
      label: item.label,
      stages: item.stages || [],
      methods: [],
      stage_custom: item.stage_custom || 0,
      method_custom: 0,
      keyword_custom: 0,
      custom_count: item.custom_count || 0,
      mood: true,
      saveAction: "mood_prompt_save",
      resetAction: "mood_prompt_reset",
      bodyKey: "mood",
    }));
    return groups;
  }

  function moodZones(p) {
    return extraZones(p);
  }

  function allEditorZones(p, withMood = true) {
    return [...(promptData(p).zones || []), ...(withMood ? extraZones(p) : [])];
  }

  function editorHintText(p) {
    const data = promptData(p);
    const total = data.custom_total || 0;
    const words = data.keyword_custom_total || 0;
    const moods = moodZones(p).reduce((sum, item) => sum + (item.custom_count || 0), 0);
    return "三栏：「阶段（程度）」初起/发烫/将溢 · 「方式（动作）」乳交/舔/吮吸… · "
      + "「关键词」自动判断方式用的词；左边最下面还有「欲望度 / 羞耻度」四段 · "
      + (total || words || moods
        ? `现在提示词改了 ${total} 处、关键词改了 ${words} 个、日常情绪改了 ${moods} 段`
        : "现在全部用内置默认")
      + " · 改完立刻生效";
  }

  function editorZoneEntry(p, zone) {
    const zones = allEditorZones(p);
    return zones.find((item) => item.key === zone) || zones[0] || null;
  }

  async function editorPost(body) {
    if (!VIEW) VIEW = await waitForBridge();
    if (!VIEW || typeof VIEW.apiPost !== "function") throw new Error("当前环境不支持调用");
    const res = await VIEW.apiPost(API_ACTION, body);
    if (res && res.ok === false) throw new Error(res.error || res.message || "保存失败");
    if (res && res.data) state = res.data;
    return res || {};
  }

  function openEditor() {
    if (!state || !state.sub_prompts) {
      toast("后端还是旧版本：重载「受孕」插件后就能改提示词");
      return;
    }
    editor.open = true;
    editor.dirty = false;
    editor.drafts = {};
    document.body.classList.add("is-editing");
    $("promptEditor").hidden = false;
    $("promptEditor").classList.add("is-open");
    editor.zone = editor.zone || (promptData(state).zones || [])[0]?.key || "";
    renderEditor();
  }

  /* 点「返回」：有没保存的字先问一句（保存并返回 / 不保存返回 / 继续编辑） */
  /* 弹窗没人理就自己关：10 秒没点任何按钮 → 按「不保存返回」处理 */
  const EXIT_DIALOG_IDLE_MS = 10000;
  let dialogTimer = null;

  function openEditorDialog() {
    $("editorConfirm").hidden = false;
    clearTimeout(dialogTimer);
    dialogTimer = setTimeout(() => {
      if ($("editorConfirm").hidden) return;
      editor.dirty = false;
      closeEditorNow();
      toast("10 秒没操作，已按「不保存返回」关掉（这段字没存）");
    }, EXIT_DIALOG_IDLE_MS);
  }

  function closeEditorDialog() {
    clearTimeout(dialogTimer);
    dialogTimer = null;
    $("editorConfirm").hidden = true;
  }

  function closeEditor() {
    if (editor.saving || editor.dirty) {
      openEditorDialog();
      return;
    }
    closeEditorNow();
  }

  function closeEditorNow() {
    closeEditorDialog();
    editor.dirty = false;
    editor.open = false;
    document.body.classList.remove("is-editing");
    $("promptEditor").hidden = true;
    $("promptEditor").classList.remove("is-open");
    $("uterusEditor").hidden = true;
    $("uterusEditor").classList.remove("is-open");
    $("tuneEditor").hidden = true;
    $("tuneEditor").classList.remove("is-open");
    $("wetnessEditor").hidden = true;
    $("wetnessEditor").classList.remove("is-open");
    $("surpriseEditor").hidden = true;
    $("surpriseEditor").classList.remove("is-open");
    ["behaviorEditor", "clothingEditor", "swallowEditor", "squirtEditor",
     "condomEditor", "unbirthEditor", "insertEditor", "birthEditor",
     "zoneKeywordsEditor", "lewdEditor"].forEach((id) => {
      const el = $(id);
      if (el) {
        el.hidden = true;
        el.classList.remove("is-open");
      }
    });
    if (state) render(state);
  }

  /* ---------------- 子宫设置（撑开 + 充盈/溢出提示词） ---------------- */

  const UTERUS_TUNE_KEYS = {
    stretch_at: "ueStretchAt",
    stretch_ratio: "ueStretchRatio",
    after_leak_per_hour: "ueAfterLeakRate",
    after_leak_until: "ueAfterLeakUntil",
  };

  function openUterusEditor() {
    if (!state || !state.fill_prompts) {
      toast("后端还是旧版本：重载「受孕」插件后就能设置");
      return;
    }
    document.body.classList.add("is-editing");
    $("uterusEditor").hidden = false;
    $("uterusEditor").classList.add("is-open");
    renderUterusEditor();
  }

  function closeUterusEditor() {
    document.body.classList.remove("is-editing");
    $("uterusEditor").hidden = true;
    $("uterusEditor").classList.remove("is-open");
    if (state) render(state);
  }

  function ueCardHtml(kind, item, max) {
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.kind = kind;
    card.dataset.level = String(item.level);
    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = item.title;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text ue-text";
    area.dataset.kind = kind;
    area.dataset.level = String(item.level);
    area.maxLength = max;
    area.rows = 3;
    area.value = item.value || "";
    area.addEventListener("input", () => {
      count.textContent = `${area.value.length}/${max}`;
      card.classList.add("is-dirty");
      $("uterusEditorStatus").textContent = "未保存…";
      $("uterusEditorStatus").dataset.tone = "warn";
    });

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.ueResetField = `${kind}:${item.level}`;
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  function renderUterusEditor() {
    const data = state || {};
    const tune = (data.tuning || {}).uterus || {};
    const manual = tune.manual || {};
    const max = promptData(data).max_len || 400;
    Object.entries(UTERUS_TUNE_KEYS).forEach(([key, id]) => {
      const input = $(id);
      if (!input) return;
      if (document.activeElement !== input) input.value = tune[key] ?? "";
      input.classList.toggle("manual", !!manual[key]);
    });
    const now = data.uterus || {};
    $("ueStretchNote").textContent = manual.stretch_at || manual.stretch_ratio
      ? "（有改过的项）" : "（跟随配置）";
    $("ueNow").textContent =
      `装了 ${fixed(now.ml, 1)} / ${fixed(now.capacity_effective ?? now.capacity, 0)} ml`
      + `（${now.level_title || "空"}）`
      + (Number(now.stretch) > 0 ? ` · 正撑开 +${fixed(now.stretch_percent, 0)}%` : "");
    if ($("ueAfterLeak")) {
      $("ueAfterLeak").checked = now.after_leak_enabled !== false;
      $("ueAfterLeakText").textContent = now.after_leak_enabled === false ? "关" : "开";
    }
    $("ueAfterLeakNote").textContent = now.after_leak_enabled === false
      ? "（关着：只靠吸收，不会漏）"
      : `（${fixed(now.after_leak_per_hour, 0)} ml/小时，漏到 ${fixed(now.after_leak_until, 0)}% 停）`;

    const groups = (data.fill_prompts || []);
    const fill = groups.find((row) => row.key === "level");
    const overflow = groups.find((row) => row.key === "overflow");
    [["ueFillCards", fill], ["ueOverflowCards", overflow]].forEach(([id, group]) => {
      const box = $(id);
      if (!box) return;
      box.innerHTML = "";
      ((group || {}).stages || []).forEach((item) => {
        box.appendChild(ueCardHtml(group.key, item, max));
      });
    });
    const fillCustom = (fill && fill.custom_count) || 0;
    const overflowCustom = (overflow && overflow.custom_count) || 0;
    $("uterusEditorHint").textContent = fillCustom || overflowCustom
      ? `充盈改过 ${fillCustom} 段 · 溢出改过 ${overflowCustom} 段`
      : "短暂撑开的范围，以及装了不同量时她是什么感觉";
    $("uterusEditorStatus").textContent = "已保存";
    $("uterusEditorStatus").dataset.tone = "ok";
  }

  async function saveUterusPrompts(kind, boxId) {
    const box = $(boxId);
    if (!box) return;
    const texts = Array.from(box.querySelectorAll(".ue-text")).map((el) => el.value);
    try {
      await editorPost({ action: "fill_prompt_save", kind, texts });
      toast("已保存");
      renderUterusEditor();
    } catch (error) {
      toast(`保存失败：${(error && error.message) || error}`);
    }
  }

  /* 「保存并返回」：按钮先变「保存改动中…」，最多等 20 秒
     - 20 秒内成功：按钮变「保存成功」→ 正常返回
     - 超时：先正常返回，再飘一条「仍在保存中…」；等它真正落地时再飘一条（成功/失败）
     - 20 秒内失败：留在弹窗，按钮变「保存失败，点这里重试」（可以重试 / 不保存返回） */
  const EXIT_SAVE_LIMIT_MS = 20000;

  async function editorSaveAndClose() {
    const saveBtn = $("ecSave");
    const discardBtn = $("ecDiscard");
    const cancelBtn = $("ecCancel");
    const lock = (locked) => {
      if (saveBtn) saveBtn.disabled = locked;
      if (discardBtn) discardBtn.disabled = locked;
      if (cancelBtn) cancelBtn.disabled = locked;
    };
    if (saveBtn) saveBtn.textContent = "保存改动中…";
    lock(true);
    clearTimeout(dialogTimer);  // 已经点了，就别再自动关
    dialogTimer = null;
    const result = await saveEditor(true, false, EXIT_SAVE_LIMIT_MS)
      .catch(() => ({ status: "fail", settle: null }));

    if (result.status === "ok" || result.status === "partial") {
      if (saveBtn) saveBtn.textContent = "保存成功";
      lock(false);
      setTimeout(() => { closeEditorNow(); }, 550);
      // 兜底：万一上面那次没关掉，1.5 秒后强关，别把弹窗卡在「保存成功」
      setTimeout(() => { if (editor.open) closeEditorNow(); }, 1500);
      return;
    }
    if (result.status === "timeout") {
      // 等太久了：先让她走，再飘提示；保存真正落地时再飘一条
      closeEditorNow();
      toast("仍在保存中…");
      if (result.settle) {
        result.settle.then((rows) => {
          const bad = Array.isArray(rows) ? rows.filter((row) => row.status === "rejected") : [];
          if (bad.length) {
            const reason = (bad[0].reason && bad[0].reason.message) || "服务端/网络问题";
            toast(`保存没成功：${reason}`);
          } else {
            toast("已保存");
          }
        });
      }
      return;
    }
    if (result.status === "busy" || result.status === "skipped") {
      // 没有真发请求（比如本来就没改动）：直接返回
      closeEditorNow();
      return;
    }
    // 限时内失败：留在弹窗，让她自己决定重试还是丢下
    if (saveBtn) saveBtn.textContent = "保存失败，点这里重试";
    lock(false);
    editorStatus(`保存失败：${result.error || "服务端/网络问题"}`, "bad");
  }

  /* 编辑页：两张表——「阶段」是程度（初起/发烫/将溢），「方式」是动作（乳交/舔/吮吸…）。
     亲吻、耳朵没有方式，就只有「阶段」一张表（页签整个不显示）。 */
  /* 编辑页三栏：阶段（程度）/ 方式（动作）/ 关键词（自动判断用什么词）
     亲吻没有方式，就只有「阶段」一栏（页签整个不显示）。 */
  function renderEditorTabs(zone) {
    const tabs = $("editorTabs");
    tabs.innerHTML = "";
    const counts = {
      stage: zone ? zone.stage_custom || 0 : 0,
      method: zone ? zone.method_custom || 0 : 0,
      keywords: zone ? zone.keyword_custom || 0 : 0,
    };
    const hasMethods = !!(zone && (zone.methods || []).length);
    const entries = [["stage", "阶段（程度）"]];
    if (hasMethods) {
      entries.push(["method", "方式（动作）"]);
      entries.push(["keywords", "关键词"]);
    }
    entries.forEach(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `et-tab${editor.tab === key ? " is-on" : ""}`;
      button.dataset.tab = key;
      button.textContent = label;
      if (counts[key]) {
        const mark = document.createElement("i");
        mark.className = "et-dot";
        mark.textContent = String(counts[key]);
        button.appendChild(mark);
      }
      tabs.appendChild(button);
    });
    tabs.hidden = !hasMethods;
  }

  function stageCardHtml(zone, item, kind, max) {
    const isMethod = kind === "method";
    const card = document.createElement("article");
    card.className = `stage-card${item.custom ? " is-custom" : ""}`;
    card.dataset.kind = kind;
    card.dataset.key = isMethod ? item.key : String(item.level);

    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = isMethod ? `${item.label}（怎么弄）` : item.title;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.custom ? " is-custom" : ""}`;
    flag.textContent = item.custom ? "自定义" : "内置默认";
    const count = document.createElement("span");
    count.className = "stage-count";
    count.textContent = `${(item.value || "").length}/${max}`;
    head.append(title, flag, count);

    const area = document.createElement("textarea");
    area.className = "stage-text";
    area.rows = 3;
    area.maxLength = max;
    area.value = item.value || "";
    area.placeholder = item.default;
    area.dataset.kind = kind;
    area.dataset.key = isMethod ? item.key : String(item.level);
    area.setAttribute("aria-label", `${zone ? zone.label : ""} ${isMethod ? item.label : item.title}`);

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.default}`;
    origin.title = item.default;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.resetKind = kind;
    reset.dataset.resetKey = isMethod ? item.key : String(item.level);
    reset.textContent = "恢复这段默认";
    foot.append(origin, reset);

    card.append(head, area, foot);
    return card;
  }

  /* 关键词那一栏：一个方式一行输入（逗号/顿号分隔），清空 = 这个方式不自动判断 */
  function keywordCardHtml(zone, item) {
    const card = document.createElement("article");
    card.className = `stage-card kw-card${item.keywords_custom ? " is-custom" : ""}`;
    card.dataset.kind = "keywords";
    card.dataset.key = item.key;

    const head = document.createElement("div");
    head.className = "stage-head";
    const title = document.createElement("b");
    title.textContent = `${item.label}（自动判断用什么词）`;
    const flag = document.createElement("span");
    flag.className = `stage-badge${item.keywords_custom ? " is-custom" : ""}`;
    flag.textContent = item.keywords_custom ? "自定义" : "内置默认";
    head.append(title, flag);

    const input = document.createElement("input");
    input.type = "text";
    input.className = "kw-input";
    input.value = item.keywords_text || "";
    input.placeholder = "逗号或顿号分隔；清空 = 这个方式不自动判断";
    input.dataset.kind = "keywords";
    input.dataset.key = item.key;
    input.setAttribute("aria-label", `${zone ? zone.label : ""} ${item.label} 关键词`);

    const foot = document.createElement("div");
    foot.className = "stage-foot";
    const origin = document.createElement("span");
    origin.className = "stage-default";
    origin.textContent = `默认：${item.keywords_default_text || "（空）"}`;
    origin.title = item.keywords_default_text || "";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "link-btn";
    reset.dataset.resetKind = "keywords";
    reset.dataset.resetKey = item.key;
    reset.textContent = "恢复默认关键词";
    foot.append(origin, reset);

    card.append(head, input, foot);
    return card;
  }

  function renderEditor() {
    const data = promptData(state);
    const zones = allEditorZones(state);
    if (!zones.length) {
      $("editorZoneTitle").textContent = "读不到提示词";
      $("editorZoneMeta").textContent = "重载插件后重试";
      $("editorStages").innerHTML = "";
      return;
    }
    const zone = editorZoneEntry(state, editor.zone);
    if (zone) editor.zone = zone.key;
    if (!zone || !(zone.methods || []).length) editor.tab = "stage";

    const nav = $("editorZones");
    nav.innerHTML = "";
    zones.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `ez-item${item.key === editor.zone ? " is-on" : ""}`
        + (item.mood ? " is-mood" : "");
      button.dataset.zone = item.key;
      const name = document.createElement("span");
      name.textContent = item.label;
      button.appendChild(name);
      if (item.custom_count) {
        const dot = document.createElement("i");
        dot.className = "ez-dot";
        dot.textContent = String(item.custom_count);
        button.appendChild(dot);
      }
      nav.appendChild(button);
    });

    $("editorZoneTitle").textContent = zone ? zone.label : "—";
    $("editorZoneMeta").textContent = !zone
      ? "—"
      : zone.mood
        ? `四段改过 ${zone.stage_custom || 0} 段`
          + (zone.custom_count ? "" : "（全是内置默认）")
        : `阶段改过 ${zone.stage_custom || 0} 段 · 方式改过 ${zone.method_custom || 0} 个`
          + ` · 关键词改过 ${zone.keyword_custom || 0} 个`
          + (zone.custom_count || zone.keyword_custom ? "" : "（全是内置默认）");

    if (zone && zone.mood) {
      $("editorTabs").hidden = true;
      $("editorTabs").innerHTML = "";
    } else {
      renderEditorTabs(zone);
    }

    const list = $("editorStages");
    list.innerHTML = "";
    const max = data.max_len || 400;
    if (editor.tab === "keywords" && !(zone && zone.mood)) {
      (zone ? zone.methods || [] : []).forEach((item) => {
        list.appendChild(keywordCardHtml(zone, item));
      });
    } else if (editor.tab === "method" && !(zone && zone.mood)) {
      (zone ? zone.methods || [] : []).forEach((item) => {
        list.appendChild(stageCardHtml(zone, item, "method", max));
      });
    } else {
      (zone ? zone.stages || [] : []).forEach((item) => {
        list.appendChild(stageCardHtml(zone, item, "stage", max));
      });
    }

    // 有草稿（还没确认写进服务端）就把草稿盖回去，服务端慢也不会显示旧字
    applyEditorDraft();
    editor.dirty = !!editor.drafts[editorKey()];
    $("editorHint").textContent = editorHintText(state);
    $("editorNote").textContent = editor.tab === "keywords" && !(zone && zone.mood)
      ? "改完点「保存」或切换部位时写入；逗号/顿号分隔；清空 = 这个方式不自动判断"
      : "改完点「保存」或切换部位时写入；留空 = 用回内置默认";
    $("btnEditorSave").textContent = zone && zone.mood
      ? "保存这四段"
      : ({
        stage: "保存这三段",
        method: "保存这些方式",
        keywords: "保存这些关键词",
      }[editor.tab] || "保存");
    const customTotal = promptData(state).custom_total || 0;
    const keywordTotal = promptData(state).keyword_custom_total || 0;
    const moodTotal = moodZones(state).reduce((sum, item) => sum + (item.custom_count || 0), 0);
    const total = customTotal + keywordTotal + moodTotal;
    if (editor.pending) {
      // 后台正在写：别被"已自定义 N 处"盖掉，不然看不出保存还在路上
      editorStatus("正在保存改动…", "muted");
    } else if (editor.dirty) {
      editorStatus("未保存…（切换部位或点保存时写入）", "warn");
    } else {
      editorStatus(total ? `已自定义 ${total} 处` : "全部内置默认", total ? "ok" : "muted");
    }
  }

  function editorStatus(text, tone) {
    const el = $("editorStatus");
    el.textContent = text;
    el.dataset.tone = tone || "muted";
  }

  /* 当前 tab 里所有输入框（顺序和 payload 里的 stages/methods 一致） */
  function editorFields() {
    if (editor.tab === "keywords") {
      return Array.from(document.querySelectorAll("#editorStages .kw-input"))
        .map((el) => ({ kind: "keywords", key: el.dataset.key, value: el.value }));
    }
    return Array.from(document.querySelectorAll("#editorStages .stage-text"))
      .map((el) => ({ kind: el.dataset.kind, key: el.dataset.key, value: el.value }));
  }

  /* 打字时只标记"未保存"，不再每敲一下就发请求：
     真正写入发生在 切换部位 / 切换页签 / 点保存 / 返回 / 关闭页面 的时候。
     同时把当前这一页的文字记成草稿：服务端慢、还没回执时切回来也不会看到旧字。 */
  function markEditorDirty() {
    editor.dirty = true;
    editor.drafts[editorKey()] = editorFields().map((field) => field.value);
    editorStatus("未保存…（切换部位或点保存时写入）", "warn");
  }

  /* 渲染完某一页后，把草稿盖回去（只在还没存成功时存在） */
  function applyEditorDraft() {
    const draft = editor.drafts[editorKey()];
    if (!draft || !draft.length) return;
    const fields = Array.from(document.querySelectorAll(
      "#editorStages .stage-text, #editorStages .kw-input"));
    fields.forEach((el, index) => {
      if (draft[index] !== undefined) el.value = draft[index];
    });
    const max = promptData(state).max_len || 400;
    document.querySelectorAll("#editorStages .stage-card").forEach((card, index) => {
      const count = card.querySelector(".stage-count");
      const area = card.querySelector(".stage-text");
      if (count && area) count.textContent = `${area.value.length}/${max}`;
    });
  }

  function raceTimeout(promise, ms) {
    return Promise.race([
      promise,
      new Promise((resolve, reject) => setTimeout(() => reject(new Error("timeout")), ms)),
    ]);
  }

  /* background=true：发出去就走人（切部位 / 返回 / 关页面用），服务端慢也不卡界面
     background=false：等回执（点「保存」用），带超时，超时也不算丢字 */
  async function saveEditor(force, background = false, timeoutMs = 8000) {
    clearTimeout(editor.timer);
    if (!editor.open) return { status: "skipped", settle: null };
    if (!background) {
      if (editor.saving) return { status: "busy", settle: null };
      if (!editor.dirty && !force) return { status: "ok", settle: null };
    }
    const zone = editorZoneEntry(state, editor.zone);
    if (!zone) return { status: "ok", settle: null };
    // 先抓住输入框本身（不是值），再让输入法上屏：这样哪怕这期间界面已经切走/重画，
    // 读到的还是"点保存那一刻"的那几段字。
    const boxes = Array.from(document.querySelectorAll(
      "#editorStages .stage-text, #editorStages .kw-input"));
    const snapshotKey = editorKey(zone.key, editor.tab);
    const seq = ++editor.saveSeq;
    const saveBtn = $("btnEditorSave");
    // 标记**在 await 之前**就改掉：这页的字已经发出去（或即将发出），
    // 这样晚到的回包不会把别的页的"未保存"状态抹掉
    if (!background) {
      editor.saving = true;
      if (saveBtn) saveBtn.disabled = true;
      editorStatus("正在保存改动…", "muted");
    } else {
      if (editorKey() === snapshotKey) editor.dirty = false;
      editor.pending = (editor.pending || 0) + 1;
      editorStatus("正在保存改动…", "muted");
    }
    const active = document.activeElement;
    const stageBox = $("editorStages");
    if (active && typeof active.blur === "function" && stageBox && stageBox.contains(active)) {
      active.blur();
      // 让输入法把最后几个字落进输入框（只在这一步等一帧，不卡界面）
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    const fields = boxes.map((el) => ({ kind: el.dataset.kind, key: el.dataset.key, value: el.value }));
    const draftKey = snapshotKey;
    const snapshot = fields.map((field) => field.value).join("\u0000");
    const jobs = [];
    const post = (body) => {
      const job = editorPost(body).then((res) => {
        // 只认最后一次保存的回执，免得旧的把新状态盖回去
        if (seq === editor.saveSeq && res && res.data) {
          state = res.data;
          if (!editor.open) render(state);
        }
        return res;
      });
      jobs.push(job);
      return job;
    };

    try {
      if (zone.mood) {
        post({
          action: zone.saveAction || "mood_prompt_save",
          [zone.bodyKey || "mood"]: zone.raw,
          texts: fields.map((field) => field.value),
        });
      } else if (editor.tab === "keywords") {
        for (const field of fields) {
          post({
            action: "sub_keywords_save",
            zone: zone.key,
            method: field.key,
            keywords: field.value,
          });
        }
      } else if (editor.tab === "method") {
        // 方式表：一个方式一句，逐条存
        for (const field of fields) {
          post({
            action: "sub_prompt_save",
            zone: zone.key,
            method: field.key,
            text: field.value,
          });
        }
      } else {
        post({
          action: "sub_prompt_save",
          zone: zone.key,
          texts: fields.map((field) => field.value),
        });
      }

      if (background) {
        // 后台写入：脏标记已经在发出去之前清掉了；这里只把草稿更新成本次发出的版本
        if (editor.drafts[draftKey]) {
          editor.drafts[draftKey] = fields.map((field) => field.value);
        }
        Promise.allSettled(jobs).then((results) => {
          editor.pending = Math.max(0, (editor.pending || 1) - 1);
          const failed = results.filter((row) => row.status === "rejected");
          const stamp = new Date().toLocaleTimeString();
          if (!failed.length) {
            delete editor.drafts[draftKey];
            if (editor.open && editorKey() === draftKey) {
              syncEditorCards(zone.key);
              renderEditorNav();
            }
            if (editor.open) {
              editorStatus(editor.pending
                ? "正在保存改动…"
                : (editor.dirty ? `${stamp} 已存上一处；当前这段还没存`
                  : `已保存 ${stamp}`),
                editor.pending || editor.dirty ? "warn" : "ok");
            }
            return;
          }
          const reason = (failed[0].reason && failed[0].reason.message) || "服务端慢/网络问题";
          toast(`有 ${failed.length} 处没存上（${reason}）——回到这一段点「保存」重试`);
          if (editor.open && editorKey() === draftKey) editor.dirty = true;
          if (editor.open) {
            editorStatus(`有 ${failed.length} 处没存上：回到那一段点「保存」重试`, "bad");
          }
        });
        return { status: "queued", settle: Promise.allSettled(jobs) };
      }

      // 前台：等回执（点「保存」8 秒、弹窗里「保存并返回」20 秒）；超时也不判失败
      const settle = Promise.allSettled(jobs).then((rows) => {
        const bad = rows.filter((row) => row.status === "rejected");
        return bad.length
          ? { ok: false, reason: (bad[0].reason && bad[0].reason.message) || "保存失败" }
          : { ok: true };
      });
      const settled = await raceTimeout(settle, timeoutMs).catch(() => null);
      if (!settled) {
        if (editorKey() === draftKey) editor.dirty = false;
        editorStatus("已提交，回执有点慢：字在服务端会写进去，过几秒刷新看看", "warn");
        return { status: "timeout", settle };
      }
      if (!settled.ok) throw new Error(settled.reason || "保存失败");
      const stillSame = editorFields().map((field) => field.value).join("\u0000") === snapshot;
      if (stillSame) {
        if (editorKey() === draftKey) editor.dirty = false;
        delete editor.drafts[draftKey];
      }
      syncEditorCards(zone.key);
      renderEditorNav();
      const mismatch = stillSame ? editorMismatch(zone.key, snapshot) : 0;
      if (!stillSame) {
        editorStatus("保存了刚才那版；现在的改动还没存", "warn");
      } else if (mismatch) {
        editor.dirty = true;
        editorStatus(`服务端有 ${mismatch} 段和输入框不一致`
          + "（可能输入法还没上屏：再点一次保存）", "warn");
      } else {
        editorStatus(`已保存 ${new Date().toLocaleTimeString()}`, "ok");
      }
      return { status: editor.dirty ? "partial" : "ok", settle };
    } catch (error) {
      editorStatus(`保存失败：${(error && error.message) || error}`, "bad");
      return { status: "fail", error: (error && error.message) || String(error), settle: null };
    } finally {
      if (!background) {
        editor.saving = false;
        if (saveBtn) saveBtn.disabled = false;
      }
    }
  }

  /* 保存后核对一下服务端存下来的文字是不是我们刚发的那份（不一致 = 上屏/截断） */
  function editorMismatch(zoneKey, snapshot) {
    const zone = editorZoneEntry(state, zoneKey);
    if (!zone || editor.tab !== "stage") return 0;
    const sent = String(snapshot || "").split("\u0000");
    return (zone.stages || []).reduce((count, item, index) => {
      const value = String(item && item.value !== undefined ? item.value : "");
      return count + (value === (sent[index] === undefined ? "" : sent[index]) ? 0 : 1);
    }, 0);
  }

  /* 保存后只更新徽标/字数，**不碰输入框里已经敲好的字**（
     以前这里会写回服务端值，遇到输入法还没上屏就会把末尾"吃掉"） */
  function syncEditorCards(zoneKey) {
    const zone = editorZoneEntry(state, zoneKey);
    if (!zone) return;
    const max = promptData(state).max_len || 400;
    const keywordTab = editor.tab === "keywords";
    const items = keywordTab
      ? (zone.methods || [])
      : (editor.tab === "method" ? (zone.methods || []) : (zone.stages || []));
    document.querySelectorAll("#editorStages .stage-card").forEach((card, index) => {
      const item = items[index];
      if (!item) return;
      const custom = keywordTab ? item.keywords_custom : item.custom;
      card.classList.toggle("is-custom", custom);
      const flag = card.querySelector(".stage-badge");
      if (flag) {
        flag.textContent = custom ? "自定义" : "内置默认";
        flag.classList.toggle("is-custom", custom);
      }
      if (!keywordTab) {
        const area = card.querySelector(".stage-text");
        const count = card.querySelector(".stage-count");
        if (count && area) count.textContent = `${area.value.length}/${max}`;
      }
    });
    $("editorZoneMeta").textContent = zone.mood
      ? `四段改过 ${zone.stage_custom || 0} 段`
        + (zone.custom_count ? "" : "（全是内置默认）")
      : `阶段改过 ${zone.stage_custom || 0} 段 · 方式改过 ${zone.method_custom || 0} 个`
        + ` · 关键词改过 ${zone.keyword_custom || 0} 个`
        + (zone.custom_count || zone.keyword_custom ? "" : "（全是内置默认）");
    if (!zone.mood) renderEditorTabs(zone);
  }

  /* 左侧列表的自定义小点（保存/切部位后刷新） */
  function renderEditorNav() {
    allEditorZones(state).forEach((zone) => {
      const button = document.querySelector(`.ez-item[data-zone="${zone.key}"]`);
      if (!button) return;
      const dot = button.querySelector(".ez-dot");
      if (zone.custom_count) {
        if (!dot) {
          const mark = document.createElement("i");
          mark.className = "ez-dot";
          mark.textContent = String(zone.custom_count);
          button.appendChild(mark);
        } else {
          dot.textContent = String(zone.custom_count);
        }
      } else if (dot) {
        dot.remove();
      }
    });
  }

  /* 切部位 / 切页签 / 返回：把这一页丢给后台写，界面立刻走（服务端慢也不卡） */
  function queueEditorSave() {
    if (editor.dirty) {
      saveEditor(true, true);
    }
  }

  function selectEditorZone(key) {
    if (!key || key === editor.zone) return;
    queueEditorSave();
    editor.zone = key;
    editor.tab = "stage";
    renderEditor();
  }

  function selectEditorTab(key) {
    if (!key || key === editor.tab) return;
    if (editor.saving) return;
    queueEditorSave();
    editor.tab = key;
    renderEditor();
  }

  /* 恢复默认前把这段的草稿扔掉，免得渲染时又把旧字盖回来 */
  function clearEditorDrafts(zoneKey) {
    Object.keys(editor.drafts).forEach((key) => {
      if (!zoneKey || key.startsWith(`${zoneKey}:`)) delete editor.drafts[key];
    });
  }

  async function resetEditorZone() {
    const zone = editorZoneEntry(state, editor.zone);
    if (!zone) return;
    const what = zone.mood ? "四段提示词" : "阶段、方式和关键词";
    if (!window.confirm(`把「${zone.label}」的${what}全部恢复成内置默认？`)) return;
    try {
      if (zone.mood) {
        await editorPost({
          action: zone.resetAction || "mood_prompt_reset",
          [zone.bodyKey || "mood"]: zone.raw,
        });
      } else {
        await editorPost({ action: "sub_prompt_reset", zone: zone.key });
        await editorPost({ action: "sub_keywords_reset", zone: zone.key });
      }
      clearEditorDrafts(zone.key);
      renderEditor();
      editorStatus("已恢复本部位默认", "ok");
    } catch (error) {
      editorStatus(`恢复失败：${(error && error.message) || error}`, "bad");
    }
  }

  async function resetEditorAll() {
    if (!window.confirm("把所有敏感点、方式关键词、日常情绪的提示词都恢复成内置默认？（子宫充盈/溢出在「子宫设置」页里单独恢复）")) return;
    try {
      await editorPost({ action: "sub_prompt_reset" });
      await editorPost({ action: "sub_keywords_reset" });
      await editorPost({ action: "mood_prompt_reset" });
      clearEditorDrafts();
      renderEditor();
      editorStatus("已全部恢复默认", "ok");
    } catch (error) {
      editorStatus(`恢复失败：${(error && error.message) || error}`, "bad");
    }
  }

  async function resetEditorField(kind, key) {
    const zone = editorZoneEntry(state, editor.zone);
    if (!zone) return;
    const isKeyword = kind === "keywords";
    let body;
    if (zone.mood) {
      body = {
        action: zone.resetAction || "mood_prompt_reset",
        [zone.bodyKey || "mood"]: zone.raw,
        level: Number(key),
      };
    } else {
      body = { action: isKeyword ? "sub_keywords_reset" : "sub_prompt_reset", zone: zone.key };
      if (kind === "method" || isKeyword) body.method = key;
      else body.level = Number(key);
    }
    try {
      await editorPost(body);
      const draft = editor.drafts[editorKey(zone.key, editor.tab)];
      if (draft) {
        const index = Number(key) - 1;
        if (!isKeyword && editor.tab === "stage" && index >= 0 && index < draft.length) {
          draft[index] = "";
        } else {
          delete editor.drafts[editorKey(zone.key, editor.tab)];
        }
      }
      editor.dirty = false;
      renderEditor();
      editorStatus(isKeyword ? "已恢复默认关键词" : "已恢复这段默认", "ok");
    } catch (error) {
      editorStatus(`恢复失败：${(error && error.message) || error}`, "bad");
    }
  }

  /* 日常情绪：欲望度 / 羞耻度（各 4 段，满了各有后果） */
  function renderLewd(p) {
    const data = p.lewd || {};
    if (!$("lewdValue")) return;
    if (data.enabled === undefined) {
      $("lewdValue").textContent = "—";
      $("lewdTier").textContent = "旧版";
      $("lewdMax").textContent = "100";
      $("lewdFill").style.width = "0%";
      $("lewdHint").textContent = "后端还是旧版本：重载后才会出现";
      return;
    }
    if (!data.enabled) {
      $("lewdValue").textContent = "—";
      $("lewdTier").textContent = "关";
      $("lewdMax").textContent = "—";
      $("lewdFill").style.width = "0%";
      $("lewdHint").textContent = "淫乱度关着（配置 lewd.enabled）";
      return;
    }
    const value = Number(data.value) || 0;
    $("lewdValue").textContent = fixed(value, 0);
    $("lewdMax").textContent = fixed(data.max || 100, 0);
    $("lewdTier").textContent = value >= (data.tick_min || 30) ? "发烫" : "平静";
    $("lewdFill").style.width = `${Math.max(0, Math.min(100, Number(data.percent) || 0))}%`;
    $("lewdHint").textContent = `每 ${data.tick_minutes || 20} 分钟涨一次欲望/湿润`
      + `｜高于 ${fixed(data.tick_min, 0)} 才涨，每次消耗 ${fixed(data.cost_per_tick, 0)}`
      + `｜${data.decay_after_minutes || 0} 分钟没涨后每小时退 ${fixed(data.decay_per_hour, 0)}`;
  }

  function renderNightRaid(p) {
    const block = $("nightRaidBlock");
    if (!block) return;
    const data = p.night_raid || {};
    const f = data.forecast || {};
    if (!f.phase) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    if ($("nrPcStay")) {
      $("nrPcStay").checked = data.pc_stay_up_enabled !== false;
      $("nrPcStayText").textContent = data.pc_stay_up_enabled === false ? "关" : "开";
      $("nrFishStay").checked = data.fish_stay_up_enabled !== false;
      $("nrFishStayText").textContent = data.fish_stay_up_enabled === false ? "关" : "开";
    }
    const badge = $("nrBadge");
    badge.textContent = f.label || "—";
    badge.dataset.tone = f.phase === "pending" ? "warn"
      : f.phase === "forecast" && (f.chance || 0) >= 50 ? "ok"
        : f.phase === "blocked" || f.phase === "off" ? "muted" : "muted";
    let text = `窗口 ${f.at || "—"}–${f.end || "—"}`;
    if (f.minutes_to > 0) text += `｜约 ${f.minutes_to} 分钟后`;
    else text += "｜窗口内";
    if (f.phase === "forecast") text += `｜预计 ${f.chance}%`;
    if (f.reason) text += `｜${f.reason}`;
    if (f.desire_parts) {
      text += "｜欲望来源：" + Object.entries(f.desire_parts)
        .map(([name, value]) => `${name} ${value}`).join(" / ");
    }
    if (f.phase === "forecast" && f.pc_late === false) {
      text += `（PC 没熬夜，淫乱度给的熬夜机会 ${f.late_chance}%）`;
    }
    $("nrHint").textContent = text;
  }

  function renderDesireStrategy(p) {
    const block = $("desireStrategyBlock");
    const box = $("desireStrategyRows");
    if (!block || !box) return;
    const data = p.desire_strategy || {};
    const rows = Array.isArray(data.features) ? data.features : [];
    if (!rows.length) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    box.textContent = "";
    rows.forEach((item) => {
      const row = document.createElement("div");
      row.className = "desire-strategy-row";
      const label = document.createElement("span");
      label.textContent = item.label;
      row.appendChild(label);
      const select = document.createElement("select");
      select.dataset.desireFeature = item.key;
      (item.options || []).forEach((option) => {
        const opt = document.createElement("option");
        opt.value = option.key;
        opt.textContent = option.label;
        if (option.key === item.value) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener("change", async () => {
        const result = await sendAction("desire_set",
          { feature: item.key, value: select.value }).catch(() => null);
        if (result) { toast(result); await load(false); }
      });
      row.appendChild(select);
      box.appendChild(row);
    });
  }

  function renderMood(p) {
    const data = p.mood || {};
    const list = $("moodList");
    const period = data.shame_period || {};
    badge($("moodBadge"),
      !data.enabled ? "关" : period.active ? `羞耻期 ${period.remaining}′` : "日常",
      !data.enabled ? "off" : period.active ? "warn" : "ok");
    $("moodHint").textContent = !data.enabled
      ? "配置 mood.enabled 关着"
      : period.active
        ? "羞耻期里她自己不肯用玩具，先哄哄她"
        : "欲望满了会转成正式场景；羞耻满了会进羞耻期";
    list.innerHTML = "";
    if (!data.enabled) {
      $("moodNote").textContent = "日常情绪关着（配置 mood.enabled）。";
      return;
    }
    [["desire", "欲望度"], ["shame", "羞耻度"]].forEach(([key, label]) => {
      const row = data[key] || {};
      const li = document.createElement("li");
      li.className = "mood-row";
      li.dataset.key = key;
      li.dataset.level = String(row.level || 0);

      const head = document.createElement("div");
      head.className = "m-head";

      const name = document.createElement("span");
      name.className = "m-name";
      name.textContent = label;

      const level = document.createElement("span");
      level.className = `m-level${row.level ? "" : " is-idle"}`;
      level.textContent = row.title || "无";
      level.title = row.prompt || "";

      const minus = document.createElement("button");
      minus.type = "button";
      minus.className = "m-btn";
      minus.dataset.action = "mood_adjust";
      minus.dataset.mood = key;
      minus.dataset.delta = "-5";
      minus.textContent = "−";
      minus.title = `${label} −5`;

      const value = document.createElement("span");
      value.className = "m-value";
      value.textContent = fixed(row.value, 0);

      const plus = document.createElement("button");
      plus.type = "button";
      plus.className = "m-btn";
      plus.dataset.action = "mood_adjust";
      plus.dataset.mood = key;
      plus.dataset.delta = "5";
      plus.textContent = "＋";
      plus.title = `${label} +5`;

      head.append(name, level, minus, value, plus);

      const progress = document.createElement("div");
      progress.className = "mood-progress";
      const progressFill = document.createElement("i");
      setWidth(progressFill, row.percent || 0);
      const progressText = document.createElement("span");
      progressText.textContent = `${fixed(row.value, 0)} / 100`;
      progress.append(progressFill, progressText);

      const prompt = document.createElement("p");
      prompt.className = "m-prompt";
      prompt.textContent = row.prompt || "还没起来";
      prompt.title = row.prompt || "";

      li.append(head, progress, prompt);
      list.appendChild(li);
    });
    const bits = [];
    bits.push(`欲望满了会转成正式场景（回落到 ${data.full_reset?.desire ?? 30}）`);
    bits.push(`羞耻满了进羞耻期（回落到 ${data.full_reset?.shame ?? 35}）`);
    if (data.fish_available) {
      bits.push(`鱼之心责怪 ${fixed(data.fish_blame, 1)}`
        + (data.fish_write ? "（「道歉」每按一次 −" + fixed(data.apology_blame, 1) + "）"
                           : "（写鱼之心的开关关着）"));
    } else {
      bits.push("读不到鱼之心（责怪改不了）");
    }
    if (period.active) bits.push(`这次羞耻期还剩 ${period.remaining} 分钟（玩具不可用）`);
    else bits.push("安慰 / 摸摸头 / 亲吻 / 正常日常 / 时间 都会降羞耻");
    $("moodNote").textContent = bits.join(" · ");
    const apology = $("btnApology");
    if (apology) {
      apology.textContent = `道歉（责怪 −${fixed(data.apology_blame ?? 4, 0)}）`;
      apology.disabled = !(data.fish_available && data.fish_write);
      apology.title = apology.disabled
        ? "读不到鱼之心或写开关关着：改不了它的责怪"
        : `帮鱼之心把责怪降 ${fixed(data.apology_blame ?? 4, 1)}（每次）`;
    }
    const blameInput = $("shameBlameInput");
    if (blameInput && document.activeElement !== blameInput) {
      blameInput.value = fixed(data.shame_blame ?? 0, 1);
    }
    if (blameInput) blameInput.classList.toggle("manual", !!data.shame_blame_manual);
    $("shameBlameHint").textContent = data.shame_blame_manual
      ? `已改（配置值 +${fixed(data.shame_blame_config ?? 0, 1)}）`
      : "";
  }

  function renderToys(p) {
    const list = $("toyList");
    const rows = p.toys || [];
    const active = p.toy || null;
    const selfUse = p.toy_self || {};
    if ($("toySelfUse")) {
      $("toySelfUse").checked = selfUse.enabled !== false;
      $("toySelfUseText").textContent = selfUse.enabled === false ? "关" : "开";
    }
    const select = $("toyIntensity");
    const level = select ? Number(select.value) || 2 : 2;
    const zoneNames = { vulva: "外阴", vagina: "阴道", anus: "肛", nipple: "乳头",
                        gspot: "G点", cervix: "子宫颈", mouth: "嘴" };
    list.innerHTML = "";
    $("toyEmpty").hidden = rows.length > 0;
    $("toyNote").textContent = active
      ? `${active.label}（${active.intensity_label}）还在她身上，大约还剩 ${active.remaining} 分钟。`
      : "用一次只涨快感、不判定受孕；用过会在身上留一段状态。";
    const activeKey = active ? active.key : "";
    rows.forEach((row) => {
      const isActive = row.active || row.key === activeKey;
      const li = document.createElement("li");
      li.className = `toy-row${row.enabled ? "" : " is-off"}${isActive ? " is-active" : ""}`;

      const name = document.createElement("span");
      name.className = "t-label";
      name.textContent = row.label;

      const place = document.createElement("span");
      place.className = "t-place-wrap";
      const places = row.places || [];
      if (places.length > 1) {
        const placeSelect = document.createElement("select");
        placeSelect.className = "t-place";
        placeSelect.dataset.toy = row.key;
        places.forEach((item) => {
          const option = document.createElement("option");
          option.value = item.key;
          option.textContent = item.label;
          if (isActive && row.place === item.key) option.selected = true;
          placeSelect.appendChild(option);
        });
        place.appendChild(placeSelect);
      } else {
        const zone = document.createElement("span");
        zone.className = "t-zone";
        zone.textContent = zoneNames[row.zone] || row.zone || "";
        place.appendChild(zone);
      }
      if (row.outside) {
        const outside = document.createElement("span");
        outside.className = "t-outside";
        outside.textContent = "日常";
        place.appendChild(outside);
      }

      const gain = document.createElement("span");
      gain.className = "t-gain";
      const values = row.gains || {};
      gain.textContent = row.enabled ? `+${fixed(values[level] ?? row.gain, 1)}` : "—";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "t-use";
      if (isActive) {
        button.dataset.action = "toy_stop";
        button.textContent = "停";
        button.title = "把玩具收起来";
      } else {
        button.dataset.action = "toy";
        button.dataset.toy = row.key;
        button.textContent = "用";
        button.title = `用一次 ${row.label}`;
      }
      button.disabled = !row.enabled;

      li.append(name, place, gain, button);
      list.appendChild(li);
    });
  }

  function renderSources(p) {
    const sources = p.sources || {};
    const fish = sources.fish || {};
    const dark = sources.dark || {};
    $("ownerHint").textContent = `欲望归属：${sources.owner || "—"}`;

    const fishOn = !!fish.usable;
    $("fishDot").className = `dot ${fishOn ? "ok" : fish.available ? "warn" : "off"}`;
    $("fishState").textContent = fishOn
      ? `启用 · 欲 ${fixed(fish.desire, 1)}${fish.awakened ? "" : "（未解锁）"}`
      : fish.available ? "未启用" : "读不到";
    setWidth($("fishFill"), pct(fish.desire, 100));
    $("fishFill").style.background = "linear-gradient(90deg, #f6ad55, #f0708c)";
    $("fishFill").classList.toggle("dim", !fishOn);
    $("fishNote").textContent = !fishOn
      ? "插件未激活或总开关关闭，受孕率里按 ×1.00 算"
      : !fish.adult_enabled
        ? "成人层总开关关着（可以在鱼之心面板打开，或用 /受孕同意 临时授权）"
        : fish.adult_open
          ? "成人层已打开（她正处在同意/场景里）"
          : "成人层已允许（总开关开）";

    const darkOn = !!dark.usable;
    $("darkDot").className = `dot ${darkOn ? "ok" : dark.available ? "warn" : "off"}`;
    $("darkState").textContent = darkOn
      ? `启用 · lust ${fixed(dark.lust, 1)}`
      : dark.available ? "未接管" : "读不到";
    setWidth($("darkFill"), pct(dark.lust, 100));
    $("darkFill").style.background = "linear-gradient(90deg, #a78bfa, #7dd3fc)";
    $("darkFill").classList.toggle("dim", !darkOn);
    $("darkNote").textContent = darkOn
      ? "引擎在跑，受孕率里按实际 lust 计算"
      : (dark.reason || "归属不是暗涌或引擎没在跑，按 ×1.00 算");
  }

  function renderLog(p) {
    const list = $("logList");
    const rows = p.log || [];
    list.innerHTML = "";
    $("logEmpty").hidden = rows.length > 0;
    rows.slice().reverse().forEach((row) => {
      const li = document.createElement("li");
      const time = document.createElement("time");
      time.textContent = timeText(row.at);
      const text = document.createElement("span");
      const kind = document.createElement("b");
      kind.className = "kind";
      kind.textContent = (KIND_CN[row.kind] || row.kind || "") + " ";
      text.append(kind, document.createTextNode(String(row.text || "")));
      li.append(time, text);
      list.appendChild(li);
    });
  }

  /* ---------------- 数据 ---------------- */

  async function load(showError = true) {
    try {
      if (!VIEW) VIEW = await waitForBridge();
      if (!VIEW || typeof VIEW.apiGet !== "function") {
        if (DEMO) {
          render(DEMO);
          $("errorCard").hidden = true;
          $("grid").hidden = false;
          return;
        }
        throw new Error(
          "等不到 AstrBot 的页面桥接脚本（/api/plugin/page/bridge-sdk.js）。\n" +
          "通常是 AstrBot 版本不支持插件页面，或这个页面被直接打开、没有经过面板。",
        );
      }
      syncTheme(VIEW);
      const res = await VIEW.apiGet(API_STATE);
      if (res && res.ok === false) throw new Error(res.error || "读取状态失败");
      const payload = res && res.data ? res.data : res;
      if (!payload || !payload.plugin) throw new Error("返回数据不完整");
      render(payload);
      $("errorCard").hidden = true;
      $("grid").hidden = false;
    } catch (error) {
      console.error(error);
      if (showError) {
        $("errorText").textContent = String((error && error.message) || error);
        $("errorCard").hidden = false;
        $("grid").hidden = true;
      }
    }
  }

  let toastTimer = null;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => { el.hidden = true; }, 260);
    }, 2600);
  }

  async function sendAction(action, body, button) {
    busy = true;
    if (button) button.disabled = true;
    try {
      if (!VIEW) VIEW = await waitForBridge();
      if (!VIEW || typeof VIEW.apiPost !== "function") {
        if (DEMO) {
          toast("这是本地预览：示例数据，不会真的操作");
          return;
        }
        throw new Error("当前环境不支持调用");
      }
      const res = await VIEW.apiPost(API_ACTION, { action, ...(body || {}) });
      if (res && res.ok === false) throw new Error(res.error || res.message || "操作失败");
      toast((res && res.message) || "完成");
      if (res && res.data && res.data.plugin) render(res.data);
      else await load(false);
    } catch (error) {
      toast(`操作失败：${(error && error.message) || error}`);
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  async function act(button) {
    if (busy) return;
    const action = button.dataset.action;
    if (!action) return;
    if (button.dataset.confirm && !window.confirm("确定要重置孕期、快感、连续高潮与子敏感度（含溢出攒的开发度/敏感度加成），并恢复 PC 周期吗？")) {
      return;
    }
    const body = { action };
    if (button.dataset.amount) body.amount = Number(button.dataset.amount);
    if (button.dataset.inside !== undefined) body.inside = button.dataset.inside === "1";
    if (button.dataset.mode) body.mode = button.dataset.mode;
    if (button.dataset.style) body.style = button.dataset.style;
    if (button.dataset.zone) {
      body.zone = button.dataset.zone;
      if (action === "touch") body.times = 1;
    }
    if (button.dataset.toy) {
      body.toy = button.dataset.toy;
      const select = $("toyIntensity");
      body.intensity = select ? Number(select.value) || 2 : 2;
      const row = button.closest(".toy-row");
      const placeSelect = row ? row.querySelector(".t-place") : null;
      if (placeSelect) body.place = placeSelect.value;
    }
    if (button.dataset.delta) body.delta = Number(button.dataset.delta);
    if (button.dataset.reset) body.reset = true;
    if (button.dataset.mood) body.mood = button.dataset.mood;
    if (button.dataset.kind) body.kind = button.dataset.kind;
    if (button.dataset.enabled !== undefined) body.enabled = button.dataset.enabled === "1";
    if (button.dataset.willing !== undefined) {
      body.willing = button.dataset.willing === "" ? null : button.dataset.willing === "1";
    }
    if (button.dataset.confirm) body.confirm = true;

    await sendAction(action, body, button);
  }

  /* ---------------- 事件 ---------------- */

  $("btnRefresh").addEventListener("click", () => load(false));
  $("btnRetry").addEventListener("click", () => load(true));

  const edgeInput = $("edgeStepInput");
  if (edgeInput) {
    edgeInput.addEventListener("change", () => {
      const value = Number(edgeInput.value);
      if (!Number.isFinite(value) || busy) return;
      sendAction("edge_step", { action: "edge_step", value }, null);
    });
  }

  const toySelect = $("toyIntensity");
  if (toySelect) {
    toySelect.addEventListener("change", () => {
      if (state) renderToys(state);
    });
  }

  $("zoneList").addEventListener("change", (event) => {
    const target = event.target;
    if (busy) return;
    if (target.matches && target.matches(".z-tail-switch input")) {
      sendAction("zone_toggle", { action: "zone_toggle", zone: "tail" }, null);
      return;
    }
    if (target.classList && target.classList.contains("z-dev-input")) {
      const dev = Number(target.value);
      if (Number.isFinite(dev)) {
        sendAction("zone_dev", { action: "zone_dev", zone: target.dataset.zone, value: dev }, null);
      }
      return;
    }
    if (target.classList && target.classList.contains("z-input")) {
      const gain = Number(target.value);
      if (Number.isFinite(gain)) {
        sendAction("zone_gain", { action: "zone_gain", zone: target.dataset.zone, value: gain }, null);
      }
    }
  });

  document.querySelectorAll(".tune-input").forEach((input) => {
    input.addEventListener("change", () => {
      const value = Number(input.value);
      if (!Number.isFinite(value) || busy) return;
      sendAction("tune", {
        action: "tune",
        section: input.dataset.section,
        key: input.dataset.key,
        value,
      }, null);
    });
  });

  if ($("uterusOverflow")) {
    $("uterusOverflow").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("uterus_overflow_toggle",
        { action: "uterus_overflow_toggle", enabled: !!event.target.checked }, null);
    });
  }

  if ($("uterusAfterLeak")) {
    $("uterusAfterLeak").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("uterus_after_leak_toggle",
        { action: "uterus_after_leak_toggle", enabled: !!event.target.checked }, null);
    });
  }
  if ($("ueAfterLeak")) {
    $("ueAfterLeak").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("uterus_after_leak_toggle",
        { action: "uterus_after_leak_toggle", enabled: !!event.target.checked }, null);
    });
  }

  if ($("succTail")) {
    $("succTail").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("succubus_tail_toggle",
        { action: "succubus_tail_toggle", enabled: !!event.target.checked }, null);
    });
  }
  const shameBlameInput = $("shameBlameInput");
  if (shameBlameInput) {
    shameBlameInput.addEventListener("change", () => {
      const value = Number(shameBlameInput.value);
      if (!Number.isFinite(value) || busy) return;
      sendAction("mood_shame_blame", { action: "mood_shame_blame", value }, null);
    });
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (button) {
      event.preventDefault();
      act(button);
    }
  });

  $("btnUterusEditor").addEventListener("click", openUterusEditor);
  $("btnUterusBack").addEventListener("click", closeUterusEditor);
  $("btnUeSaveFill").addEventListener("click", () => saveUterusPrompts("level", "ueFillCards"));
  $("btnUeSaveOverflow").addEventListener("click", () => saveUterusPrompts("overflow", "ueOverflowCards"));
  $("btnUeResetFill").addEventListener("click", async () => {
    await editorPost({ action: "fill_prompt_reset", kind: "level" }).catch(() => null);
    toast("充盈提示词已恢复默认");
    renderUterusEditor();
  });
  $("btnUeResetOverflow").addEventListener("click", async () => {
    await editorPost({ action: "fill_prompt_reset", kind: "overflow" }).catch(() => null);
    toast("溢出提示词已恢复默认");
    renderUterusEditor();
  });
  Object.entries(UTERUS_TUNE_KEYS).forEach(([key, id]) => {
    const input = $(id);
    if (!input) return;
    input.addEventListener("change", () => {
      const value = Number(input.value);
      if (!Number.isFinite(value) || busy) return;
      sendAction("tune", { action: "tune", section: "uterus", key, value }, null);
    });
  });
  $("uterusEditor").addEventListener("click", (event) => {
    const resetTune = event.target.closest("[data-ue-reset]");
    if (resetTune) {
      sendAction("tune", { action: "tune", section: "uterus",
                           key: resetTune.dataset.ueReset, reset: true }, null);
      return;
    }
    const resetField = event.target.closest("[data-ue-reset-field]");
    if (resetField) {
      const [kind, level] = resetField.dataset.ueResetField.split(":");
      editorPost({ action: "fill_prompt_reset", kind, level: Number(level) })
        .then(() => { toast("已恢复这段默认"); renderUterusEditor(); })
        .catch((error) => toast(`恢复失败：${(error && error.message) || error}`));
    }
  });

  $("btnEnduranceSettings").addEventListener("click", () => openTuneEditor("endurance"));
  $("btnTunePushConfig").addEventListener("click", async () => {
    if (!window.confirm("把面板当前数值和开关写回配置页？\n会直接改 AstrBot 的插件配置文件。")) return;
    const result = await sendAction("config_sync_push", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnTuneFollowConfig").addEventListener("click", async () => {
    if (!window.confirm("清除所有面板覆盖，全部改回配置页的数值？\n面板里单独改过的数值和开关都会丢。")) return;
    const result = await sendAction("tuning_clear_all", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("pillBlame").addEventListener("change", async () => {
    const result = await sendAction("pill_blame_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("pillBlameOnce").addEventListener("change", async () => {
    const result = await sendAction("pill_blame_once_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("pillProactive").addEventListener("change", async () => {
    const result = await sendAction("pill_proactive_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnPillPrompts").addEventListener("click", () => openBehaviorEditor("pill"));
  $("btnToySettings").addEventListener("click", () => openTuneEditor("toys"));
  $("toySelfUse").addEventListener("change", async () => {
    const result = await sendAction("toys_self_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnTuneBack").addEventListener("click", closeTuneEditor);
  if ($("weBaseFloat")) {
    $("weBaseFloat").addEventListener("change", async () => {
      const enabled = $("weBaseFloat").checked;
      await sendAction("wetness_base_float_toggle", { enabled }).catch(() => null);
      $("weBaseFloatText").textContent = enabled ? "开" : "关";
      await load(false);
    });
  }
  $("btnWetnessEditor").addEventListener("click", openWetnessEditor);
  $("btnSurpriseEditor").addEventListener("click", openSurpriseEditor);
  const swallowAction = async (action, extra = {}) => {
    const result = await sendAction(action, extra).catch(() => null);
    if (result) { toast(result); await load(false); }
  };
  $("btnInsertPrompts").addEventListener("click", () => {
    openBehaviorEditor();
    const select = $("bpGroup");
    if (select) {
      select.value = "uterus";
      renderBehaviorCards();
    }
  });
  $("btnInsertEditor").addEventListener("click", openInsertEditor);
  $("btnInsertBack").addEventListener("click", closeInsertEditor);
  $("btnPregnancySettings").addEventListener("click", openPregnancyEditor);
  $("btnPregnancyBack").addEventListener("click", closePregnancyEditor);
  $("btnPregnancyPrompts").addEventListener(
    "click", () => openBehaviorEditor("pregnancy", "pregnancy"));
  $("btnBirthEditor").addEventListener("click", openBirthEditor);
  $("btnBirthBack").addEventListener("click", closeBirthEditor);
  $("btnBirthKeywordsSave").addEventListener("click", async () => {
    const textValue = $("bsKeywords").value;
    const result = await sendAction("birth_keywords_save", { text: textValue })
      .catch(() => null);
    if (result) toast(result);
    await load(false);
  });
  $("btnUnbirthPrompts").addEventListener("click", () => {
    openBehaviorEditor();
    const select = $("bpGroup");
    if (select) {
      select.value = "unbirth";
      renderBehaviorCards();
    }
  });
  $("btnNightRaidPrompts").addEventListener("click", () => openBehaviorEditor("night_raid"));
  $("btnHymenPrompts").addEventListener("click", () => openBehaviorEditor("hymen_blood"));
  $("btnZoneKeywords").addEventListener("click", openZoneKeywordsEditor);
  $("btnZoneKeywordsBack").addEventListener("click", closeZoneKeywordsEditor);
  $("btnZoneKeywordsSaveAll").addEventListener("click", saveAllZoneKeywords);
  $("zoneKeywordRows").addEventListener("click", (event) => {
    const reset = event.target.closest("[data-zone-reset]");
    if (!reset) return;
    resetZoneKeywords(reset.dataset.zoneReset);
  });
  $("btnLewdPrompts").addEventListener(
    "click", () => openBehaviorEditor("lewd"));
  $("btnLewdEditor").addEventListener("click", openLewdEditor);
  $("btnNightRaidEditor").addEventListener("click", openLewdEditor);
  $("btnLewdBack").addEventListener("click", closeLewdEditor);
  $("btnUnbirthRequestPrompts").addEventListener(
    "click", () => openBehaviorEditor("unbirth"));
  $("ubRequest").addEventListener("change", async () => {
    const result = await sendAction("unbirth_request_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUnbirthEditor").addEventListener("click", openUnbirthEditor);
  $("btnUnbirthBack").addEventListener("click", closeUnbirthEditor);
  $("ubOn").addEventListener("change", async () => {
    const enabled = $("ubOn").checked;
    $("ubOn").dataset.pending = "1";
    $("ubOnText").textContent = enabled ? "开" : "关";
    await sendAction("unbirth_toggle", { enabled }).catch(() => null);
    await load(false);
    delete $("ubOn").dataset.pending;
    renderUnbirth(state);
  });
  $("btnCondomEditor").addEventListener("click", openCondomEditor);
  $("btnCondomBack").addEventListener("click", closeCondomEditor);
  $("nrPcStay").addEventListener("change", async () => {
    const result = await sendAction("night_stay_toggle", { key: "pc" }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("nrFishStay").addEventListener("change", async () => {
    const result = await sendAction("night_stay_toggle", { key: "fish" }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnSquirtPrompts").addEventListener(
    "click", () => openBehaviorEditor("squirt"));
  $("btnSquirtEditor").addEventListener("click", openSquirtEditor);
  $("btnSquirtBack").addEventListener("click", closeSquirtEditor);
  $("btnAsmrStart").addEventListener("click", async () => {
    const minutes = Number($("asmrMinutes").value) || 20;
    const result = await sendAction("asmr_start", { minutes }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnAsmrExtend").addEventListener("click", async () => {
    const result = await sendAction("asmr_extend", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnAsmrEnd").addEventListener("click", async () => {
    const result = await sendAction("asmr_end", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("asmrActions").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-asmr-key]");
    if (!button) return;
    const result = await sendAction("asmr_do",
      { key: button.dataset.asmrKey }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnAsmrPrompts").addEventListener(
    "click", () => openBehaviorEditor("asmr"));
  $("btnAsmrSettings").addEventListener("click", openAsmrEditor);
  $("btnAsmrBack").addEventListener("click", closeAsmrEditor);
  $("btnAsmrKeywordsSave").addEventListener("click", async () => {
    const result = await sendAction("asmr_keywords_save",
      { text: $("asmrKnownKeywords").value }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnAsmrEditorPrompts").addEventListener("click", () => {
    closeAsmrEditor();
    openBehaviorEditor("asmr");
  });
  $("asmrEnabled").addEventListener("change", async () => {
    const result = await sendAction("asmr_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("asmrRequestEnabled").addEventListener("change", async () => {
    const result = await sendAction("asmr_request_toggle", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnSwallowEditor").addEventListener("click", openSwallowEditor);
  $("btnSwallowBack").addEventListener("click", closeSwallowEditor);
  $("btnSwallowPrompts").addEventListener(
    "click", () => openBehaviorEditor("swallow", "swallow"));
  $("swAuto").addEventListener("change", async () => {
    const enabled = $("swAuto").checked;
    await sendAction("swallow_auto_toggle", { enabled }).catch(() => null);
    $("swAutoText").textContent = enabled ? "开" : "关";
    await load(false);
  });
  $("btnSwCollect").addEventListener("click", () => swallowAction("swallow_collect"));
  $("btnSwMouth").addEventListener("click",
    () => swallowAction("swallow_collect", { in_mouth: true }));
  $("btnSwSwallow").addEventListener("click", () => swallowAction("swallow_swallow"));
  const unbirthAction = async (action, extra = {}) => {
    const result = await sendAction(action, extra).catch(() => null);
    if (result) { toast(result); await load(false); }
  };
  const ubHymen = () => ($("ubHymenMode") ? $("ubHymenMode").value : "pass");
  $("btnUbShrink").addEventListener("click", () => unbirthAction("unbirth_shrink"));
  $("btnUbGrow").addEventListener("click", () => unbirthAction("unbirth_grow"));
  $("btnUbRestore").addEventListener("click", () => unbirthAction("unbirth_restore"));
  $("btnSleepInsideAsk").addEventListener("click",
    () => unbirthAction("sleep_inside_ask", { mode: $("sleepInsideMode").value }));
  $("btnSleepInsideAccept").addEventListener("click",
    () => unbirthAction("sleep_inside_accept"));
  $("btnSleepInsideEnd").addEventListener("click",
    () => unbirthAction("sleep_inside_end"));
  $("btnSleepInsideSlight").addEventListener("click",
    () => unbirthAction("sleep_inside_move", { deep: false }));
  $("btnSleepInsideDeep").addEventListener("click",
    () => unbirthAction("sleep_inside_move", { deep: true }));
  $("btnMenstrualSettings").addEventListener("click", () => {
    const info = ((state && state.cycle) || {}).menstrual || {};
    const cfg = info.settings || {};
    $("msNoticeText").value = cfg.notice_text || "";
    $("msNoticeDefault").textContent = cfg.notice_default || "";
    $("msNoticeBadge").textContent = cfg.notice_text ? "自定义" : "默认";
    $("msFlow").value = cfg.flow_ml_per_hour ?? 4;
    $("msJitter").value = cfg.flow_jitter ?? 0.35;
    $("msBloodCapacity").value = cfg.capacity_ml ?? 60;
    $("msDrain").value = cfg.drain_ml_per_hour ?? 8;
    $("msNoticeChance").value = cfg.pad_notice_chance ?? 100;
    $("msWarnMinutes").value = cfg.pad_warn_minutes ?? 2;
    $("msChangeMinutes").value = cfg.pad_change_minutes ?? 2;
    $("msChangePercent").value = cfg.change_at_percent ?? 80;
    $("msChangeMin").value = cfg.change_min_minutes ?? 30;
    const models = cfg.pad_models || {};
    $("msLiner").value = models.liner ?? 8;
    $("msRegular").value = models.regular ?? 20;
    $("msNight").value = models.night ?? 35;
    $("msPants").value = models.pants ?? 60;
    $("msAutoChoose").checked = cfg.pad_auto_choose !== false;
    $("msAutoChooseText").textContent = cfg.pad_auto_choose === false ? "关" : "开";
    document.body.classList.add("is-editing");
    window.scrollTo(0, 0);
    $("menstrualSettingsEditor").hidden = false;
    $("menstrualSettingsEditor").classList.add("is-open");
  });
  $("btnMsNoticeRestore").addEventListener("click", () => {
    $("msNoticeText").value = $("msNoticeDefault").textContent || "";
  });
  $("btnMenstrualSettingsBack").addEventListener("click", () => {
    $("menstrualSettingsEditor").hidden = true;
    $("menstrualSettingsEditor").classList.remove("is-open");
    document.body.classList.remove("is-editing");
  });
  $("btnMenstrualSettingsSave").addEventListener("click", async () => {
    const settings = {
      notice_text: $("msNoticeText").value,
      flow_ml_per_hour: Number($("msFlow").value),
      flow_jitter: Number($("msJitter").value),
      capacity_ml: Number($("msBloodCapacity").value),
      drain_ml_per_hour: Number($("msDrain").value),
      pad_notice_chance: Number($("msNoticeChance").value),
      pad_warn_minutes: Number($("msWarnMinutes").value),
      pad_change_minutes: Number($("msChangeMinutes").value),
      change_at_percent: Number($("msChangePercent").value),
      change_min_minutes: Number($("msChangeMin").value),
      pad_auto_choose: $("msAutoChoose").checked,
      pad_models: {
        liner: Number($("msLiner").value),
        regular: Number($("msRegular").value),
        night: Number($("msNight").value),
        pants: Number($("msPants").value),
      },
    };
    const result = await sendAction("menstrual_settings_save", { settings }).catch(() => null);
    if (result) {
      toast(result);
      $("menstrualSettingsEditor").hidden = true;
      $("menstrualSettingsEditor").classList.remove("is-open");
      document.body.classList.remove("is-editing");
      await load(false);
    }
  });
  $("btnSleepInsideKeywords").addEventListener("click", () => {
    document.body.classList.add("is-editing");
    window.scrollTo(0, 0);
    $("sleepInsideKeywordsEditor").hidden = false;
    $("sleepInsideKeywordsEditor").classList.add("is-open");
  });
  $("btnSleepInsideKeywordsBack").addEventListener("click", () => {
    $("sleepInsideKeywordsEditor").hidden = true;
    $("sleepInsideKeywordsEditor").classList.remove("is-open");
    document.body.classList.remove("is-editing");
  });
  $("btnSleepInsideKeywordsSave").addEventListener("click", async () => {
    const keywords = {
      vagina: $("siKwVagina").value,
      anus: $("siKwAnus").value,
      tail: $("siKwTail").value,
      unbirth: $("siKwUnbirth").value,
    };
    const result = await sendAction("sleep_inside_keywords_save", { keywords }).catch(() => null);
    if (result) {
      toast(result);
      $("sleepInsideKeywordsEditor").hidden = true;
      $("sleepInsideKeywordsEditor").classList.remove("is-open");
      document.body.classList.remove("is-editing");
      await load(false);
    }
  });
  $("childCareMode").addEventListener("change", async () => {
    const result = await sendAction("children_set_care",
      { mode: $("childCareMode").value }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("childInterrupt").addEventListener("change", async () => {
    const result = await sendAction("children_interrupt_toggle").catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUbEnter").addEventListener("click", () =>
    unbirthAction("unbirth_enter", { hymen_mode: ubHymen() }));
  $("btnUbTube").addEventListener("click", () =>
    unbirthAction("unbirth_enter", { hymen_mode: ubHymen(), location: "tube" }));
  $("btnUbOvary").addEventListener("click", () =>
    unbirthAction("unbirth_enter", { hymen_mode: ubHymen(), location: "ovary" }));
  $("btnUbExit").addEventListener("click", () =>
    unbirthAction("unbirth_exit", { hymen_mode: ubHymen() }));
  $("btnUbBirth").addEventListener("click", () =>
    unbirthAction("unbirth_birth", { hymen_mode: ubHymen() }));
  $("btnUbResistWordsSave").addEventListener("click", async () => {
    const result = await sendAction("unbirth_keywords_save",
      { text: $("ubResistWords").value }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUbResist").addEventListener("click", () =>
    unbirthAction("unbirth_birth", { hymen_mode: ubHymen(), resist: true }));
  ["ubHeight", "ubWeight"].forEach((id) => {
    const input = $(id);
    if (!input) return;
    input.addEventListener("change", async () => {
      const height = Number($("ubHeight").value) || 170;
      const weight = Number($("ubWeight").value) || 60;
      await sendAction("unbirth_body", { height_cm: height, weight_kg: weight })
        .catch(() => null);
      await load(false);
    });
  });
  $("btnClothingEditor").addEventListener("click", openClothingEditor);
  $("btnClothingBack").addEventListener("click", closeClothingEditor);
  $("btnMoodCooldown").addEventListener("click", () => {
    const panel = $("moodCooldownPanel");
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      const input = $("moodCooldownMinutes");
      if (input) input.focus();
    }
  });
  $("btnSurpriseKinds").addEventListener("click", () => {
    openBehaviorEditor();
    const select = $("bpGroup");
    if (select) {
      select.value = "surprise_kind";
      renderBehaviorCards();
    }
  });
  $("btnSizePrompts").addEventListener("click", () => {
    openBehaviorEditor();
    const select = $("bpGroup");
    if (select) {
      select.value = "size";
      renderBehaviorCards();
    }
  });
  $("btnCyclePrompts").addEventListener("click", () =>
    openBehaviorEditor("cycle", "cycle"));
  $("cyclePromptsOn").addEventListener("change", async () => {
    const result = await sendAction("cycle_prompts_toggle").catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnClothingPrompts").addEventListener("click", () =>
    openBehaviorEditor("clothing", "clothing"));
  $("clothingSlots").addEventListener("click", (event) => {
    const refresh = event.target.closest(".clothing-refresh");
    if (refresh) {
      sendAction("outfit_refresh", { slot: refresh.dataset.slot }).catch(() => null);
      return;
    }
    const chip = event.target.closest(".clothing-chip");
    if (!chip) return;
    if (!chip.dataset.key) {
      if (chip.dataset.worn !== "1") return;
      outfitAction(chip.dataset.slot, "", true);
      return;
    }
    outfitAction(chip.dataset.slot, chip.dataset.key, chip.dataset.worn === "1");
  });
  $("btnBirthComfort").addEventListener("click", async () => {
    const result = await sendAction("birth_comfort", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("comboPlus").addEventListener("click", async () => {
    await sendAction("combo_step", { delta: 1 }).catch(() => null);
    await load(false);
  });
  $("comboMinus").addEventListener("click", async () => {
    await sendAction("combo_step", { delta: -1 }).catch(() => null);
    await load(false);
  });
  $("btnCondomWear").addEventListener("click", async () => {
    const result = await sendAction("condom_wear", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnCondomRenew").addEventListener("click", async () => {
    const result = await sendAction("condom_renew", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnCondomHelp").addEventListener("click", async () => {
    const result = await sendAction("condom_help", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnCondomRemove").addEventListener("click", async () => {
    const result = await sendAction("condom_remove", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnCondomHelpRemove").addEventListener("click", async () => {
    const result = await sendAction("condom_help_remove", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnLube").addEventListener("click", async () => {
    const result = await sendAction("lube_apply", { hand: false }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnLubeHand").addEventListener("click", async () => {
    const result = await sendAction("lube_apply", { hand: true }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnLubeBreast").addEventListener("click", async () => {
    const result = await sendAction("lube_apply", { part: "breast" }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnLubeNipple").addEventListener("click", async () => {
    const result = await sendAction("lube_apply", { part: "nipple" }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnLubePenis").addEventListener("click", async () => {
    const result = await sendAction("lube_apply", { part: "penis" }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUsEnter").addEventListener("click", async () => {
    const result = await sendAction("uterus_enter", { force: false }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUsForce").addEventListener("click", async () => {
    const result = await sendAction("uterus_enter", { force: true }).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnUsExit").addEventListener("click", async () => {
    const result = await sendAction("uterus_exit", {}).catch(() => null);
    if (result) { toast(result); await load(false); }
  });
  $("btnBehaviorPrompts").addEventListener("click", openBehaviorEditor);
  $("btnBehaviorBack").addEventListener("click", closeBehaviorEditor);
  $("btnBehaviorKeywords").addEventListener("click", () =>
    openKeywordEditor($("btnBehaviorKeywords").dataset.group || ""));
  $("btnKeywordBack").addEventListener("click", closeKeywordEditor);
  $("btnKeywordSave").addEventListener("click", saveKeywordEditor);
  $("btnBpSave").addEventListener("click", saveBehaviorGroup);
  $("btnBpReset").addEventListener("click", async () => {
    const group = behaviorGroupNow();
    if (!group) return;
    await editorPost({ action: "behavior_prompt_reset", group: group.key }).catch(() => null);
    toast("这一组已恢复默认");
    await load(false);
    renderBehaviorGroups();
    renderBehaviorCards();
  });
  $("bpGroup").addEventListener("change", renderBehaviorCards);
  $("behaviorEditor").addEventListener("click", async (event) => {
    const resetField = event.target.closest("[data-bp-reset]");
    if (!resetField) return;
    const group = behaviorGroupNow();
    if (!group) return;
    await editorPost({ action: "behavior_prompt_reset", group: group.key,
                       key: resetField.dataset.bpReset }).catch(() => null);
    toast("已恢复这段默认");
    await load(false);
    renderBehaviorGroups();
    renderBehaviorCards();
  });
  $("btnSurpriseBack").addEventListener("click", closeSurpriseEditor);
  $("btnSeSave").addEventListener("click", saveSurprisePrompts);
  $("btnSeSaveMessage").addEventListener("click", async () => {
    const text = $("seMessage").value.trim();
    await editorPost({ action: "surprise_message_save", text }).catch(() => null);
    toast(text ? "主动消息已保存" : "已清空，回到内置短句");
    renderSurpriseEditor();
  });
  $("btnSeReset").addEventListener("click", async () => {
    await editorPost({ action: "surprise_prompt_reset" }).catch(() => null);
    toast("突然被弄提示词已恢复默认");
    renderSurpriseEditor();
  });
  $("surpriseEditor").addEventListener("click", (event) => {
    const resetField = event.target.closest("[data-se-reset-field]");
    if (resetField) {
      editorPost({ action: "surprise_prompt_reset", stage: resetField.dataset.seResetField })
        .then(() => { toast("已恢复这段默认"); renderSurpriseEditor(); })
        .catch((error) => toast(`恢复失败：${(error && error.message) || error}`));
      return;
    }
    const reset = event.target.closest(".tune-reset");
    if (!reset) return;
    sendAction("tune", { action: "tune", section: reset.dataset.section,
                         key: reset.dataset.key, reset: true }, null);
  });
  if ($("surpriseOn")) {
    $("surpriseOn").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("surprise_toggle",
        { action: "surprise_toggle", enabled: !!event.target.checked }, null);
    });
  }
  if ($("sleepAllow")) {
    $("sleepAllow").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("sleep_allow_toggle",
        { action: "sleep_allow_toggle", enabled: !!event.target.checked }, null);
    });
  }
  if ($("sleepBlock")) {
    $("sleepBlock").addEventListener("click", (event) => {
      const reset = event.target.closest(".sleep-reset");
      if (!reset) return;
      sendAction("tune", { action: "tune", section: reset.dataset.section,
                           key: reset.dataset.key, reset: true }, null);
    });
  }
  $("btnWetnessBack").addEventListener("click", closeWetnessEditor);
  $("btnWeSave").addEventListener("click", saveWetnessPrompts);
  $("btnWeReset").addEventListener("click", async () => {
    await editorPost({ action: "wetness_prompt_reset" }).catch(() => null);
    toast("湿润度提示词已恢复默认");
    renderWetnessEditor();
  });
  if ($("weFishWrite")) {
    $("weFishWrite").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("wetness_fish_toggle",
        { action: "wetness_fish_toggle", enabled: !!event.target.checked }, null);
    });
  }
  $("wetnessEditor").addEventListener("click", (event) => {
    const resetField = event.target.closest("[data-we-reset-field]");
    if (resetField) {
      editorPost({ action: "wetness_prompt_reset",
                   level: Number(resetField.dataset.weResetField) })
        .then(() => { toast("已恢复这段默认"); renderWetnessEditor(); })
        .catch((error) => toast(`恢复失败：${(error && error.message) || error}`));
      return;
    }
    const reset = event.target.closest(".tune-reset");
    if (!reset) return;
    sendAction("tune", {
      action: "tune",
      section: reset.dataset.section,
      key: reset.dataset.key,
      reset: true,
    }, null);
  });
  $("btnTeSaveEndurance").addEventListener("click", saveEndurancePrompts);
  if ($("teRotateTimer")) {
    $("teRotateTimer").addEventListener("change", (event) => {
      if (busy) return;
      sendAction("special_rotate_toggle",
        { action: "special_rotate_toggle", enabled: !!event.target.checked }, null);
    });
  }
  $("btnTeResetEndurance").addEventListener("click", async () => {
    await editorPost({ action: "endurance_prompt_reset" }).catch(() => null);
    toast("忍耐条提示词已恢复默认");
    renderEndurancePrompts();
  });
  $("tuneEditor").addEventListener("click", (event) => {
    const resetField = event.target.closest("[data-te-reset-field]");
    if (resetField) {
      editorPost({ action: "endurance_prompt_reset",
                   level: Number(resetField.dataset.teResetField) })
        .then(() => { toast("已恢复这段默认"); renderEndurancePrompts(); })
        .catch((error) => toast(`恢复失败：${(error && error.message) || error}`));
      return;
    }
    const reset = event.target.closest(".tune-reset");
    if (!reset) return;
    sendAction("tune", {
      action: "tune",
      section: reset.dataset.section,
      key: reset.dataset.key,
      reset: true,
    }, null);
  });

  /* ---------------- 敏感点阶段性表现（编辑页）事件 ---------------- */

  $("btnPromptEditor").addEventListener("click", openEditor);
  $("btnEditorBack").addEventListener("click", closeEditor);
  $("btnEditorSave").addEventListener("click", () => saveEditor(true));
  $("btnEditorResetZone").addEventListener("click", resetEditorZone);
  $("btnEditorResetAll").addEventListener("click", resetEditorAll);
  $("ecSave").addEventListener("click", editorSaveAndClose);
  $("ecDiscard").addEventListener("click", () => {
    closeEditorDialog();
    editor.dirty = false;
    closeEditorNow();
  });
  $("ecCancel").addEventListener("click", () => {
    closeEditorDialog();
    editorStatus("还没存：改完点「保存」或切换部位时写入", "warn");
  });

  $("editorZones").addEventListener("click", (event) => {
    const button = event.target.closest("[data-zone]");
    if (button) selectEditorZone(button.dataset.zone);
  });

  $("editorTabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (button) selectEditorTab(button.dataset.tab);
  });

  $("editorStages").addEventListener("input", (event) => {
    const target = event.target;
    if (!target.classList) return;
    if (target.classList.contains("stage-text")) {
      const card = target.closest(".stage-card");
      const count = card ? card.querySelector(".stage-count") : null;
      if (count) count.textContent = `${target.value.length}/${promptData(state).max_len || 400}`;
    } else if (!target.classList.contains("kw-input")) {
      return;
    }
    markEditorDirty();
  });

  $("editorStages").addEventListener("click", (event) => {
    const button = event.target.closest("[data-reset-key]");
    if (button) resetEditorField(button.dataset.resetKind, button.dataset.resetKey);
  });

  /* 离开页面前把没保存的字发出去（后台写，不等回执） */
  window.addEventListener("beforeunload", () => {
    if (editor.open && editor.dirty) saveEditor(true, true);
  });

  /* 每 20 秒自动刷新一次；页面在后台时不刷。 */
  setInterval(() => {
    if (!document.hidden) load(false);
  }, 20000);

  load(true);
})();
