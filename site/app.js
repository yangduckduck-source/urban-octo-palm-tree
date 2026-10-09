(() => {
  "use strict";

  const WD = ["일", "월", "화", "수", "목", "금", "토"];
  const CAT_ORDER = ["글쓰기", "문학", "철학", "인문"];
  const $ = (s) => document.querySelector(s);

  // 서울 기준 오늘 (테스트용 ?date=YYYY-MM-DD)
  const seoulToday = () => {
    const q = new URLSearchParams(location.search).get("date");
    if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) return q;
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
  };
  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
  const diffDays = (a, b) => Math.round((parse(b) - parse(a)) / 86400000);
  const md = (s) => { const d = parse(s); return `${d.getMonth() + 1}월 ${d.getDate()}일`; };
  const mdw = (s) => `${md(s)} ${WD[parse(s).getDay()]}요일`;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");

  const TODAY = seoulToday();
  const state = {
    all: [],
    city: "전체",
    cats: new Set(CAT_ORDER),
    freeOnly: false,
    month: TODAY.slice(0, 7),
    selected: TODAY,
  };

  try {
    const saved = JSON.parse(localStorage.getItem("btc-filters") || "{}");
    if (saved.city) state.city = saved.city;
    if (Array.isArray(saved.cats) && saved.cats.length) state.cats = new Set(saved.cats);
    if (typeof saved.freeOnly === "boolean") state.freeOnly = saved.freeOnly;
  } catch (_) { /* 저장소를 못 쓰는 환경이면 기본값 */ }

  const persist = () => {
    try {
      localStorage.setItem("btc-filters", JSON.stringify({ city: state.city, cats: [...state.cats], freeOnly: state.freeOnly }));
    } catch (_) {}
  };

  const mainCat = (e) => CAT_ORDER.find((c) => (e.categories || []).includes(c)) || "인문";
  const catVar = (e) => `--cat: var(--c-${mainCat(e)})`;

  const visible = () =>
    state.all.filter((e) =>
      (state.city === "전체" || e.city === state.city) &&
      (e.categories || []).some((c) => state.cats.has(c)) &&
      (!state.freeOnly || e.price === "무료"));

  const byDate = (list) => {
    const m = new Map();
    for (const e of list) (m.get(e.date) || m.set(e.date, []).get(e.date)).push(e);
    for (const v of m.values()) v.sort((a, b) => (a.start || "99").localeCompare(b.start || "99") || b.score - a.score);
    return m;
  };

  // ── 추천 알고리즘 ──────────────────────────────
  // 점수(score)는 수집기가 매긴 '이 행사가 도움이 될 가능성'.
  // 오늘의 추천은 점수 순, 주간 추천은 점수에 가까운 날짜를 살짝 얹어 정렬한다.
  const weekEnd = (d) => addDays(d, (7 - parse(d).getDay()) % 7); // 이번 주 일요일
  const weekRank = (e) => e.score - diffDays(TODAY, e.date) * 0.8;

  function reasonOf(e) {
    const r = [];
    if ((e.categories || []).includes("글쓰기")) r.push("창작에 바로 닿는 자리");
    else if (e.format === "대담" && (e.categories || []).includes("문학")) r.push("작품을 깊게 읽는 대담");
    else if ((e.categories || []).includes("철학")) r.push("철학적 질문을 다루는 강연");
    if (e.speaker_weight >= 0.8) r.push("주목할 만한 연사");
    if (e.festival) r.push(e.festival);
    return r.slice(0, 2).join(" · ");
  }

  // ── 렌더링 ────────────────────────────────────
  const timeText = (e) => (e.start ? e.start + (e.end ? `–${e.end}` : "") : "시간 미정");
  const metaBits = (e) => [
    `<span class="badge">추천 ${e.score}</span>`,
    e.price === "무료" ? `<span class="badge soft">무료</span>` : e.price === "유료" ? `<span class="badge soft">유료</span>` : "",
    `<span>${esc(e.city)} · ${esc(e.format)}</span>`,
  ].join("");

  function card(e, withDate) {
    const why = reasonOf(e);
    return `<button class="card" style="${catVar(e)}" data-id="${esc(e.id)}">
      <div class="meta">${metaBits(e)}</div>
      <div class="title">${esc(e.title)}</div>
      <div class="place">${withDate ? esc(mdw(e.date)) + " · " : ""}${esc(timeText(e))} · ${esc(e.venue || e.city)}</div>
      ${why ? `<div class="why">${esc(why)}</div>` : ""}
    </button>`;
  }

  function renderToday(list) {
    $("#todayTitle").innerHTML = `오늘<small>${esc(mdw(TODAY))}</small>`;
    const today = list.filter((e) => e.date === TODAY).sort((a, b) => b.score - a.score);
    if (today.length) {
      $("#today").innerHTML = today.slice(0, 3).map((e) => card(e, false)).join("");
      return;
    }
    const soon = list
      .filter((e) => e.date > TODAY && diffDays(TODAY, e.date) <= 14)
      .sort((a, b) => weekRank(b) - weekRank(a))[0];
    $("#today").innerHTML = `<p class="empty">오늘은 조건에 맞는 행사가 없어요.</p>` +
      (soon ? `<p class="hint">가장 가까운 추천</p>${card(soon, true)}` : "");
  }

  function renderWeek(list) {
    const end = weekEnd(TODAY);
    let pool = list.filter((e) => e.date >= TODAY && e.date <= end);
    let label = `이번 주 추천<small>${md(TODAY)}–${md(end)}</small>`;
    if (pool.length < 3) {
      const end2 = addDays(TODAY, 7);
      pool = list.filter((e) => e.date >= TODAY && e.date <= end2);
      label = `다가오는 7일 추천<small>${md(TODAY)}–${md(end2)}</small>`;
    }
    $("#weekTitle").innerHTML = label;
    const top = pool.sort((a, b) => weekRank(b) - weekRank(a)).slice(0, 5);
    $("#week").innerHTML = top.length
      ? top.map((e, i) => `<li><button data-id="${esc(e.id)}">
          <span class="n">${i + 1}</span>
          <span><div class="t">${esc(e.title)}</div><div class="s">${esc(e.city)} · ${esc(e.venue || "")} · 추천 ${e.score}</div></span>
          <span class="d"><b>${parse(e.date).getDate()}일</b>${WD[parse(e.date).getDay()]} ${esc(e.start || "")}</span>
        </button></li>`).join("")
      : `<p class="empty">이번 주에는 조건에 맞는 행사가 없어요.</p>`;
  }

  function renderCalendar(list) {
    const [y, m] = state.month.split("-").map(Number);
    $("#monthLabel").innerHTML = `${y}년 <span>${m}월</span>`;
    const first = new Date(y, m - 1, 1);
    const start = addDays(iso(first), -first.getDay());
    const map = byDate(list);
    let html = "";
    for (let i = 0; i < 42; i++) {
      const d = addDays(start, i);
      if (i === 35 && d.slice(0, 7) !== state.month) break; // 5주로 끝나는 달
      const evs = map.get(d) || [];
      const cls = ["day", d.slice(0, 7) !== state.month && "out", d === TODAY && "today",
        d === state.selected && "sel", parse(d).getDay() === 0 && "sun"].filter(Boolean).join(" ");
      const ranked = [...evs].sort((a, b) => b.score - a.score);
      html += `<button class="${cls}" data-date="${d}" aria-label="${esc(mdw(d))} 행사 ${evs.length}건">
        <span class="num">${parse(d).getDate()}</span>
        <span class="dots">${ranked.slice(0, 4).map((e) => `<i style="${catVar(e)}"></i>`).join("")}</span>
        ${ranked.slice(0, 2).map((e) => `<span class="peek" style="${catVar(e)}">${esc(e.title)}</span>`).join("")}
        ${evs.length > 2 ? `<span class="peek more">외 ${evs.length - 2}건</span>` : ""}
      </button>`;
    }
    $("#grid").innerHTML = html;
    renderDay(map);
  }

  function renderDay(map) {
    const evs = map.get(state.selected) || [];
    $("#dayLabel").textContent = `${mdw(state.selected)} · ${evs.length ? evs.length + "건" : "일정 없음"}`;
    $("#dayEvents").innerHTML = evs.map((e) => `<button class="row" data-id="${esc(e.id)}">
        <span class="time">${esc(e.start || "미정")}${e.end ? `<small>${esc(e.end)}</small>` : ""}</span>
        <span class="body" style="${catVar(e)}"><div class="t">${esc(e.title)}</div>
        <div class="s">${esc(e.city)} · ${esc(e.venue || "")} · 추천 ${e.score}</div></span>
      </button>`).join("");
  }

  function render() {
    const list = visible();
    renderToday(list);
    renderWeek(list);
    renderCalendar(list);
  }

  // ── 상세 시트 ──────────────────────────────────
  const CONF = { "확정": "공식 안내로 확인된 일정입니다.", "보도": "기사 보도를 바탕으로 정리한 일정입니다. 신청 전 공식 안내를 확인하세요.", "추정": "날짜나 장소 일부가 추정입니다. 꼭 공식 안내를 확인하세요." };

  function openSheet(id) {
    const e = state.all.find((x) => x.id === id);
    if (!e) return;
    const fact = (k, v) => (v ? `<div><dt>${k}</dt><dd>${v}</dd></div>` : "");
    const url = safeUrl(e.url);
    $("#sheetBody").innerHTML = `
      <div class="grabber"></div>
      <button class="close" aria-label="닫기" data-close>✕</button>
      <div class="cats">${(e.categories || []).map((c) => `<span class="pill" style="--cat: var(--c-${esc(c)})">${esc(c)}</span>`).join("")}
        <span class="pill" style="--cat: var(--accent)">추천 ${e.score}</span></div>
      <h2>${esc(e.title)}</h2>
      <p class="when">${esc(mdw(e.date))} · ${esc(timeText(e))}</p>
      <dl class="facts">
        ${fact("장소", esc(`${e.city} · ${e.venue || "장소 미정"}`))}
        ${fact("연사", esc((e.speakers || []).join(", ")))}
        ${fact("도서", e.book ? `『${esc(e.book)}』` : "")}
        ${fact("행사", esc(e.festival))}
        ${fact("비용", esc([e.price, e.price_note].filter(Boolean).join(" · ")))}
        ${fact("신청", esc(e.registration))}
      </dl>
      ${e.summary ? `<p class="summary">${esc(e.summary)}</p>` : ""}
      <p class="note">${esc(CONF[e.confidence] || "")}</p>
      <div class="actions">
        ${url ? `<a class="primary" href="${esc(url)}" target="_blank" rel="noopener">공식 안내 보기</a>` : ""}
        <button class="secondary" data-ics="${esc(e.id)}" ${url ? "" : 'style="grid-column: 1 / -1"'}>캘린더에 추가</button>
      </div>`;
    const d = $("#sheet");
    if (!d.open) d.showModal();
  }

  function downloadIcs(id) {
    const e = state.all.find((x) => x.id === id);
    if (!e) return;
    const x = (s) => String(s || "").replace(/\\/g, "\\\\").replace(/[;,]/g, (c) => "\\" + c).replace(/\n/g, "\\n");
    const d = e.date.replace(/-/g, "");
    let when;
    if (e.start) {
      const [h, mi] = e.start.split(":").map(Number);
      const end = e.end || `${String(Math.min(h + 2, 23)).padStart(2, "0")}:${String(mi).padStart(2, "0")}`;
      when = [`DTSTART;TZID=Asia/Seoul:${d}T${e.start.replace(":", "")}00`, `DTEND;TZID=Asia/Seoul:${d}T${end.replace(":", "")}00`];
    } else {
      when = [`DTSTART;VALUE=DATE:${d}`, `DTEND;VALUE=DATE:${addDays(e.date, 1).replace(/-/g, "")}`];
    }
    const body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//bookTalk-calendar//KO", "BEGIN:VEVENT",
      `UID:${e.id}@booktalk-calendar`, `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}Z`, ...when,
      `SUMMARY:${x(e.title)}`, `LOCATION:${x(`${e.city} ${e.venue || ""}`)}`,
      `DESCRIPTION:${x([e.summary, e.registration, e.url].filter(Boolean).join("\n"))}`,
      "END:VEVENT", "END:VCALENDAR"].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type: "text/calendar" }));
    a.download = `${e.date}-${e.title.slice(0, 20)}.ics`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ── 이벤트 ────────────────────────────────────
  function syncControls() {
    document.querySelectorAll("#city button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.city === state.city)));
    document.querySelectorAll("#chips [data-cat]").forEach((b) => b.setAttribute("aria-pressed", String(state.cats.has(b.dataset.cat))));
    $("#freeOnly").setAttribute("aria-pressed", String(state.freeOnly));
  }

  $("#city").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.city = b.dataset.city; syncControls(); persist(); render();
  });
  $("#chips").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    if (b.id === "freeOnly") state.freeOnly = !state.freeOnly;
    else {
      const c = b.dataset.cat;
      if (state.cats.has(c) && state.cats.size > 1) state.cats.delete(c); else state.cats.add(c);
    }
    syncControls(); persist(); render();
  });
  const shiftMonth = (n) => {
    const [y, m] = state.month.split("-").map(Number);
    const d = new Date(y, m - 1 + n, 1);
    state.month = iso(d).slice(0, 7);
    renderCalendar(visible());
  };
  $("#prev").addEventListener("click", () => shiftMonth(-1));
  $("#next").addEventListener("click", () => shiftMonth(1));
  $("#goToday").addEventListener("click", () => { state.month = TODAY.slice(0, 7); state.selected = TODAY; renderCalendar(visible()); });
  $("#grid").addEventListener("click", (ev) => {
    const b = ev.target.closest(".day"); if (!b) return;
    state.selected = b.dataset.date;
    if (state.selected.slice(0, 7) !== state.month) state.month = state.selected.slice(0, 7);
    renderCalendar(visible());
  });
  document.addEventListener("click", (ev) => {
    const ics = ev.target.closest("[data-ics]");
    if (ics) return downloadIcs(ics.dataset.ics);
    if (ev.target.closest("[data-close]")) return $("#sheet").close();
    const item = ev.target.closest("[data-id]");
    if (item) openSheet(item.dataset.id);
  });
  $("#sheet").addEventListener("click", (ev) => { if (ev.target === ev.currentTarget) ev.currentTarget.close(); });

  // 구독 링크: Apple 캘린더 등에서 바로 구독되도록 webcal:// 로
  const sub = $("#subscribe");
  if (location.protocol === "https:") sub.href = new URL("calendar.ics", location.href).href.replace(/^https:/, "webcal:");

  syncControls();
  fetch("data/events.json", { cache: "no-cache" })
    .then((r) => r.json())
    .then((data) => {
      state.all = (data.events || []).filter((e) => e && e.date && e.id);
      const u = data.meta && data.meta.updated_at;
      if (u) {
        const d = new Date(u);
        $("#updated").textContent = `서울 · 청주 문학 · 글쓰기 · 철학 · 인문 강연 · ${d.getMonth() + 1}월 ${d.getDate()}일 업데이트`;
      }
      render();
    })
    .catch(() => {
      $("#today").innerHTML = `<p class="empty">일정 데이터를 불러오지 못했어요. 잠시 후 다시 열어 주세요.</p>`;
      render();
    });
})();
