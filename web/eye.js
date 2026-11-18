/* Eye 핵심 로직 (DOM 없음): 날짜, 읽는 순서, 정보 추출, 검증, 피드백.
   파이썬 패키지 eye/ 의 dates.py, layout.py, extract.py, verify.py, feedback.py 를 옮긴 것. */
(function (root) {
  "use strict";

  // ------------------------------------------------------------ 모델
  class Word {
    constructor(text, x, y, w, h, conf = 100, page = 0, ocr = true) {
      Object.assign(this, { text, x, y, w, h, conf, page, ocr });
    }
    get right() { return this.x + this.w; }
    get bottom() { return this.y + this.h; }
    get cy() { return this.y + this.h / 2; }
  }

  const HANGUL = /[가-힣]/;
  const JOINABLE = /^[가-힣0-9()[\]]{1,4}$/;
  function joinTight(a, b, lineH) {
    if (!(a.ocr && b.ocr) || b.x - a.right >= 0.3 * lineH) return false;
    if (/[([]$/.test(a.text) || /^[)\],.]/.test(b.text)) return true;
    return JOINABLE.test(a.text) && JOINABLE.test(b.text) && (HANGUL.test(a.text) || HANGUL.test(b.text));
  }
  const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[s.length >> 1] : 0; };

  class Line {
    constructor(words) { this.words = words; }
    get x() { return Math.min(...this.words.map((w) => w.x)); }
    get y() { return Math.min(...this.words.map((w) => w.y)); }
    get right() { return Math.max(...this.words.map((w) => w.right)); }
    get bottom() { return Math.max(...this.words.map((w) => w.bottom)); }
    get height() { return median(this.words.map((w) => w.h)); }
    get conf() { return Math.min(...this.words.map((w) => w.conf)); }
    get text() { return this.render(); }
    render(fmt) {
      if (!this.words.length) return "";
      fmt = fmt || ((w) => w.text);
      const lh = Math.max(...this.words.map((w) => w.h));
      let out = fmt(this.words[0]);
      for (let i = 1; i < this.words.length; i++) {
        out += (joinTight(this.words[i - 1], this.words[i], lh) ? "" : " ") + fmt(this.words[i]);
      }
      return out;
    }
  }

  class Block {
    constructor(lines, kind = "paragraph", rows = []) { Object.assign(this, { lines, kind, rows }); }
    get x() { return Math.min(...this.lines.map((l) => l.x)); }
    get y() { return Math.min(...this.lines.map((l) => l.y)); }
    get right() { return Math.max(...this.lines.map((l) => l.right)); }
    get bottom() { return Math.max(...this.lines.map((l) => l.bottom)); }
    get height() { return median(this.lines.map((l) => l.height)); }
    get text() { return this.lines.map((l) => l.text).join("\n"); }
    get words() { return this.lines.flatMap((l) => l.words); }
  }

  class Doc {
    constructor(source, kind = "image", pages = [], isScanned = false) {
      Object.assign(this, { source, kind, pages, isScanned });
    }
    get blocks() { return this.pages.flatMap((p) => p.blocks); }
    get lines() { return this.blocks.flatMap((b) => b.lines); }
    get words() { return this.lines.flatMap((l) => l.words); }
  }

  // ------------------------------------------------------------ 날짜·시간
  const WK = "월화수목금토일"; // 0 = 월요일
  const WK_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const weekday = (d) => (d.getDay() + 6) % 7;
  function mkDate(y, m, d) {
    const dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? dt : null;
  }
  const dayDiff = (a, b) =>
    Math.round((Date.UTC(a.getFullYear(), a.getMonth(), a.getDate()) - Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())) / 864e5);
  const sameDay = (a, b) => a && b && dayDiff(a, b) === 0;
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  const RE_YMD = /(^|[^\d])(\d{4})\s*(?:년|[.\-/])\s*(\d{1,2})\s*(?:월|[.\-/])\s*(\d{1,2})(?:\s*일)?(?!\d)/g;
  const RE_MDKO = /(^|[^\d])(\d{1,2})\s*월\s*(\d{1,2})\s*일/g;
  const RE_SHORT = /(^|[^\d./-])(\d{1,2})\s*([./-])\s*(\d{1,2})(?!\d|\s*[./-]\s*\d)/g;
  const RE_WKAFTER = /^\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\)|([월화수목금토일])요일|\(?\s*(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s*\)?)/i;
  const RE_TIME = /(?:(오전|오후|am|pm)\s*)?(\d{1,2})\s*(?::\s*(\d{2})|시(?!간)\s*(?:(\d{1,2})\s*분|반)?)\s*(am|pm)?/gi;

  function weekdayAfter(text, pos) {
    const m = RE_WKAFTER.exec(text.slice(pos, pos + 12));
    if (!m) return [null, pos];
    const ko = m[1] || m[2];
    if (ko) return [WK.indexOf(ko), pos + m[0].length];
    return [WK_EN.indexOf(m[3].toLowerCase().slice(0, 3)), pos + m[0].length];
  }

  function candidates(m, d, ref, wd) {
    let out = [];
    for (const y of [ref.getFullYear() - 1, ref.getFullYear(), ref.getFullYear() + 1]) {
      const dt = mkDate(y, m, d);
      if (!dt) continue;
      const delta = dayDiff(dt, ref);
      if (delta >= -120 && delta <= 300 && (wd == null || weekday(dt) === wd)) out.push(dt);
    }
    if (!out.length && wd == null) {
      const dt = mkDate(ref.getFullYear(), m, d);
      if (dt) out.push(dt);
    }
    return out.sort((a, b) => Math.abs(dayDiff(a, ref)) - Math.abs(dayDiff(b, ref)));
  }

  function* matches(re, text) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text))) {
      const start = m.index + m[1].length;
      yield { m, start, end: m.index + m[0].length, raw: m[0].slice(m[1].length) };
      if (m[0].length === 0) re.lastIndex++;
    }
  }

  function findDates(text, ref = new Date(), prefer = "MD") {
    const found = [];
    const taken = [];
    const overlaps = (a, b) => taken.some(([s, e]) => a < e && s < b);
    const R = (raw, options, chosen, certain, reason, wd, start, end) =>
      ({ raw, options, chosen, certain, reason, weekdayHint: wd, start, end });

    for (const { m, start, end: mEnd, raw } of matches(RE_YMD, text)) {
      const [wd, end] = weekdayAfter(text, mEnd);
      const dt = mkDate(+m[2], +m[3], +m[4]);
      if (!dt) continue;
      let certain = true, reason = "";
      if (wd != null && weekday(dt) !== wd) { certain = false; reason = "요일이 날짜와 맞지 않음"; }
      found.push(R(raw, [dt], dt, certain, reason, wd, start, end));
      taken.push([start, end]);
    }
    for (const { m, start, end: mEnd, raw } of matches(RE_MDKO, text)) {
      if (overlaps(start, mEnd)) continue;
      const [wd, end] = weekdayAfter(text, mEnd);
      const c = candidates(+m[2], +m[3], ref, wd);
      if (c.length) found.push(R(raw, [c[0]], c[0], true, "", wd, start, end));
      else {
        const loose = candidates(+m[2], +m[3], ref, null);
        if (loose.length) found.push(R(raw, [loose[0]], loose[0], false, "요일이 날짜와 맞지 않음", wd, start, end));
      }
      taken.push([start, end]);
    }
    for (const { m, start, end: mEnd, raw } of matches(RE_SHORT, text)) {
      if (overlaps(start, mEnd)) continue;
      const a = +m[2], sep = m[3], b = +m[4];
      const [wd, end] = weekdayAfter(text, mEnd);
      if (sep === "." && wd == null && m[4].length < 2 && !text.slice(mEnd, mEnd + 3).includes("~")) continue;
      const mdOk = a >= 1 && a <= 12 && b >= 1 && b <= 31;
      const dmOk = sep !== "." && b >= 1 && b <= 12 && a >= 1 && a <= 31 && a !== b;
      const ambiguousFormat = mdOk && dmOk;
      const interps = [...(mdOk ? [[a, b]] : []), ...(dmOk ? [[b, a]] : [])];
      if (!interps.length) continue;
      const options = [];
      for (const [mm, dd] of interps) {
        const c = candidates(mm, dd, ref, wd);
        if (c.length && !options.some((o) => sameDay(o, c[0]))) options.push(c[0]);
      }
      if (!options.length) {
        const loose = interps.map(([mm, dd]) => candidates(mm, dd, ref, null)).filter((c) => c.length).map((c) => c[0]);
        if (loose.length) {
          found.push(R(raw, loose, loose[0], false, "요일이 날짜와 맞지 않음", wd, start, end));
          taken.push([start, end]);
        }
        continue;
      }
      if (options.length === 1) {
        const reason = ambiguousFormat && wd != null ? `요일(${WK[wd]})로 판단` : "";
        found.push(R(raw, options, options[0], true, reason, wd, start, end));
      } else {
        if (prefer === "DM") options.reverse();
        found.push(R(raw, options, options[0], false, "두 가지로 읽힐 수 있는 날짜", wd, start, end));
      }
      taken.push([start, end]);
    }
    return found.sort((x, y) => x.start - y.start);
  }

  function findTimes(text) {
    const out = [];
    RE_TIME.lastIndex = 0;
    let m;
    while ((m = RE_TIME.exec(text))) {
      const digitAt = m.index + m[0].indexOf(m[2]);
      if (digitAt > 0 && /\d/.test(text[digitAt - 1])) continue;
      const ampm = (m[1] || m[5] || "").toLowerCase();
      let h = +m[2];
      const mi = m[3] ? +m[3] : m[4] ? +m[4] : m[0].includes("반") ? 30 : 0;
      if (h > 24 || mi > 59) continue;
      if ((ampm === "오후" || ampm === "pm") && h < 12) h += 12;
      if ((ampm === "오전" || ampm === "am") && h === 12) h = 0;
      out.push(`${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}`);
    }
    return out;
  }

  const formatDate = (d) => `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${WK[weekday(d)]}요일`;
  function formatTime(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    const part = h < 12 ? "오전" : "오후";
    const h12 = h >= 1 && h <= 12 ? h : h > 12 ? h - 12 : 12;
    return `${part} ${h12}시` + (m ? ` ${m}분` : "");
  }

  // ------------------------------------------------------------ 읽는 순서
  const LIST_MARK = /^\s*(?:[-•·▪▶▷●○◆◇■□※☞✔✓*]|\d{1,2}[.)]|[①-⑳]|[가-하][.)]|\(\d{1,2}\))\s*/;
  const PAGE_NO = /^\s*(?:[-–—]\s*)?(?:p\.?\s*)?\d{1,4}(?:\s*(?:\/|of)\s*\d{1,4})?(?:\s*[-–—])?\s*$|^\s*\d{1,4}\s*쪽\s*$/i;

  function vOverlap(a, b) {
    const top = Math.max(a.y, b.y), bot = Math.min(a.bottom, b.bottom);
    const h = Math.min(a.bottom - a.y, b.bottom - b.y) || 1;
    return Math.max(0, bot - top) / h;
  }

  function groupLines(words, gapFactor = 2.0) {
    const rows = [];
    for (const w of [...words].sort((a, b) => a.cy - b.cy || a.x - b.x)) {
      let placed = false;
      for (const row of rows) {
        const ref = new Line(row);
        const ratio = w.h / (ref.height || 1);
        if (vOverlap(w, ref) >= 0.5 && ratio >= 0.4 && ratio <= 2.5) { row.push(w); placed = true; break; }
      }
      if (!placed) rows.push([w]);
    }
    const lines = [];
    for (const row of rows) {
      row.sort((a, b) => a.x - b.x);
      const h = median(row.map((w) => w.h)) || 1;
      let cur = [row[0]];
      for (const w of row.slice(1)) {
        if (w.x - cur[cur.length - 1].right > gapFactor * h) { lines.push(new Line(cur)); cur = [w]; }
        else cur.push(w);
      }
      lines.push(new Line(cur));
    }
    return lines;
  }

  function rowsOf(lines) {
    const rows = [];
    for (const ln of [...lines].sort((a, b) => (a.y + a.bottom) - (b.y + b.bottom))) {
      const row = rows.find((r) => vOverlap(ln, r[0]) >= 0.5);
      if (row) row.push(ln); else rows.push([ln]);
    }
    rows.forEach((r) => r.sort((a, b) => a.x - b.x));
    return rows;
  }

  function findTables(lines) {
    const rows = rowsOf(lines);
    const tables = [];
    const used = new Set();
    let i = 0;
    while (i < rows.length) {
      if (rows[i].length < 2) { i++; continue; }
      const group = [rows[i]];
      let j = i + 1;
      while (j < rows.length && rows[j].length === rows[i].length) {
        const tol = Math.max(...rows[j].map((l) => l.height)) * 2.5;
        const last = group[group.length - 1];
        const gap = rows[j][0].y - Math.max(...last.map((l) => l.bottom));
        const aligned = last.every((a, k) => Math.abs(a.x - rows[j][k].x) < tol || Math.abs(a.right - rows[j][k].right) < tol);
        if (!aligned || gap > tol * 1.5) break;
        group.push(rows[j]); j++;
      }
      const ncols = rows[i].length;
      const shortLeft = group.reduce((s, r) => s + r[0].text.length, 0) / group.length <= 10;
      if ((ncols >= 3 && group.length >= 2) || (ncols === 2 && group.length >= 3 && shortLeft)) {
        const blkLines = group.flat();
        tables.push(new Block(blkLines, "table", group.map((r) => r.map((l) => l.text))));
        blkLines.forEach((l) => used.add(l));
        i = j;
      } else i++;
    }
    return [tables, lines.filter((l) => !used.has(l))];
  }

  function tableRows(b) {
    const out = [];
    let i = 0;
    for (const r of b.rows) { out.push(b.lines.slice(i, i + r.length)); i += r.length; }
    return out;
  }

  function groupBlocks(lines) {
    lines = [...lines].sort((a, b) => a.y - b.y || a.x - b.x);
    const parent = lines.map((_, i) => i);
    const find = (i) => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
    for (let i = 0; i < lines.length; i++) {
      const a = lines[i];
      for (let j = i + 1; j < lines.length; j++) {
        const b = lines[j];
        const h = Math.max(a.height, b.height);
        if (b.y - a.bottom > 1.2 * h) { if (b.y - a.bottom > 4 * h) break; continue; }
        if (Math.max(a.height, b.height) / Math.max(1, Math.min(a.height, b.height)) > 1.4) continue;
        const xo = Math.min(a.right, b.right) - Math.max(a.x, b.x);
        if (xo > -0.5 * h && b.y - a.bottom > -0.5 * h) parent[find(j)] = find(i);
      }
    }
    const groups = new Map();
    lines.forEach((l, i) => { const k = find(i); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(l); });
    return [...groups.values()].map((g) => new Block(g.sort((a, b) => a.y - b.y || a.x - b.x)));
  }

  function splitLists(blocks) {
    const out = [];
    for (const b of blocks) {
      if (b.kind === "table") { out.push(b); continue; }
      let cur = [], inList = false, itemX = 0;
      for (const l of b.lines) {
        const isItem = LIST_MARK.test(l.text);
        const cont = inList && !isItem && l.x > itemX + l.height * 0.5;
        const state = isItem || cont;
        if (cur.length && state !== inList) { out.push(new Block(cur)); cur = []; }
        if (isItem) itemX = l.x;
        inList = state;
        cur.push(l);
      }
      if (cur.length) out.push(new Block(cur));
    }
    return out;
  }

  function cut(blocks, axis) {
    const spans = blocks.map((b) => axis === "y" ? [b.y, b.bottom] : [b.x, b.right]).sort((a, b) => a[0] - b[0]);
    let end = spans[0][1];
    for (const [s, e] of spans.slice(1)) {
      if (s > end) {
        const mid = (s + end) / 2;
        const key = (b) => axis === "y" ? b.y : b.x;
        return [blocks.filter((b) => key(b) < mid), blocks.filter((b) => key(b) >= mid)];
      }
      end = Math.max(end, e);
    }
    return null;
  }

  function readingOrder(blocks) {
    if (blocks.length <= 1) return [...blocks];
    for (const axis of ["y", "x"]) {
      const parts = cut(blocks, axis);
      if (parts) return [...readingOrder(parts[0]), ...readingOrder(parts[1])];
    }
    return [...blocks].sort((a, b) => a.y - b.y || a.x - b.x);
  }

  function classify(blocks, bodyH) {
    for (const b of blocks) {
      if (b.kind === "table") continue;
      if (b.lines.length <= 3 && b.height >= 1.3 * bodyH) b.kind = "heading";
      else if (b.lines.filter((l) => LIST_MARK.test(l.text)).length >= Math.max(1, b.lines.length >> 1)) b.kind = "list";
      else b.kind = "paragraph";
    }
  }

  const norm = (t) => t.replace(/\s+/g, "").replace(/\d+/g, "#");
  function stripHeadersFooters(pages, margin = 0.08) {
    const inMargin = (b, p) => b.bottom < p.height * margin || b.y > p.height * (1 - margin);
    const counts = new Map();
    for (const p of pages) {
      for (const k of new Set(p.blocks.filter((b) => inMargin(b, p)).map((b) => norm(b.text)))) counts.set(k, (counts.get(k) || 0) + 1);
    }
    const repeated = new Set([...counts].filter(([, c]) => pages.length >= 2 && c >= Math.max(2, pages.length >> 1)).map(([k]) => k));
    for (const p of pages) {
      p.blocks = p.blocks.filter((b) => !(inMargin(b, p) && (PAGE_NO.test(b.text) || repeated.has(norm(b.text)))));
    }
  }

  function buildPage(words, width, height) {
    const lines = groupLines(words);
    const [tables, rest] = findTables(lines);
    let blocks = [...splitLists(groupBlocks(rest)), ...tables];
    blocks = readingOrder(blocks);
    classify(blocks, lines.length ? median(lines.map((l) => l.height)) : 1);
    return { width, height, blocks };
  }

  // ------------------------------------------------------------ 정보 추출
  const FIELD_NAMES = { title: "행사명", datetime: "일시", place: "장소", apply: "신청 방법", deadline: "마감" };
  const BULLET = "^\\s*[■□▶▷►●○◆◇•·\\-*※☞✔✓★☆◎▣\\[]?\\s*";
  const LABELS = [
    ["deadline", "(?:신청|접수|모집|지원)\\s*(?:기간|기한|마감)|마감(?:일|\\s*일시)?|기한|deadline"],
    ["datetime", "(?:행사\\s*)?(?:일\\s*시|일\\s*정|날\\s*짜|시\\s*간|기\\s*간)|행사\\s*일|when|date"],
    ["place", "(?:행사\\s*)?(?:장\\s*소|위\\s*치)|where|place|location"],
    ["title", "행사\\s*명|제\\s*목|프로그램\\s*명|주\\s*제|강연\\s*명|title"],
    ["apply", "(?:신청|접수|참여|참가|지원)\\s*(?:방법|방식|링크|처)?|apply"],
  ].map(([n, p]) => [n, new RegExp(BULLET + "(?:" + p + ")\\s*(?:\\]\\s*)?(?:[:：|]\\s*|\\s+|$)(.*)$", "i")]);
  const URL_RE = /(?:https?:\/\/|www\.)\S+|\b[\w-]+\.(?:com|kr|net|org|ly|gl|me|io)(?:\/\S*)?|forms\.gle\/\S+|bit\.ly\/\S+/i;
  const PLACE_HINT = /[가-힣A-Za-z0-9]+(?:관|홀|센터|강당|강의실|회의실|세미나실|대강당|학생회관|도서관|캠퍼스|광장|라운지|\d+호|\d+층)|온라인|비대면|zoom|줌|유튜브|youtube|webex|웹엑스|teams/i;
  const APPLY_HINT = /구글\s*폼|google\s*form|QR|큐알|링크|신청|접수|카카오\s*채널|오픈\s*채팅|이메일|e-?mail|@/i;
  const DEADLINE_HINT = /마감|까지|기한|~\s*$/;

  function matchLabel(text) {
    for (const [name, rx] of LABELS) { const m = rx.exec(text); if (m) return [name, m[1].trim()]; }
    return null;
  }

  function describe(text, readings) {
    const times = findTimes(text);
    const isRange = /[~\-–]|부터/.test(text);
    const parts = readings.filter((r) => r.chosen).map((r) => formatDate(r.chosen) + (r.certain ? "" : " (확실하지 않음)"));
    if (parts.length >= 2 && isRange) { parts[0] += "부터"; parts[1] += "까지"; }
    if (times.length) {
      if (times.length >= 2 && isRange) parts.push(`${formatTime(times[0])}부터 ${formatTime(times[1])}까지`);
      else parts.push(times.map(formatTime).join(", "));
    }
    return parts.join(" ");
  }

  function guessTitle(doc, ref, prefer) {
    const cands = [];
    for (const l of doc.lines) {
      const t = l.text.trim();
      if (t.replace(/\s/g, "").length < 2 || matchLabel(t) || findDates(t, ref, prefer).length || URL_RE.test(t)) continue;
      if (!/[가-힣A-Za-z]/.test(t)) continue;
      cands.push(l);
    }
    if (!cands.length) return [];
    const top = cands.reduce((best, l) => {
      const k = Math.round(l.height / 4), kb = Math.round(best.height / 4);
      return k > kb || (k === kb && l.y < best.y) ? l : best;
    });
    const parts = [top];
    for (const l of cands) {
      if (l === top) continue;
      const last = parts[parts.length - 1];
      if (Math.abs(l.height - top.height) <= 0.2 * top.height && l.y - last.bottom >= 0 && l.y - last.bottom <= 0.8 * top.height &&
          Math.min(l.right, top.right) > Math.max(l.x, top.x)) parts.push(l);
    }
    return parts;
  }

  function extract(doc, ref = new Date(), prefer = "MD") {
    const lines = doc.lines;
    const texts = lines.map((l) => l.text.trim());
    const fields = {};
    const put = (name, raw, withDates, src) => {
      if (fields[name] || !raw) return;
      let value = raw, readings = [];
      if (withDates) {
        readings = findDates(raw, ref, prefer);
        const desc = describe(raw, readings);
        if (desc) value = desc;
      }
      fields[name] = { name, value, raw, uncertain: readings.some((r) => !r.certain), dates: readings,
        words: src.flatMap((i) => lines[i].words) };
    };
    texts.forEach((text, i) => {
      const hit = matchLabel(text);
      if (!hit) return;
      let [name, val] = hit, src = [i];
      if (!val && i + 1 < texts.length && !matchLabel(texts[i + 1])) { val = texts[i + 1]; src = [i, i + 1]; }
      if (val) put(name, val, name === "datetime" || name === "deadline", src);
    });
    const usedDeadline = new Set();
    if (!fields.deadline) {
      const i = texts.findIndex((t) => DEADLINE_HINT.test(t) && findDates(t, ref, prefer).length);
      if (i >= 0) { put("deadline", texts[i], true, [i]); usedDeadline.add(i); }
    }
    if (!fields.datetime) {
      const i = texts.findIndex((t, k) => !usedDeadline.has(k) && !matchLabel(t) && findDates(t, ref, prefer).length);
      if (i >= 0) put("datetime", texts[i], true, [i]);
    }
    if (!fields.place) {
      const i = texts.findIndex((t) => !matchLabel(t) && PLACE_HINT.test(t) && !findDates(t, ref, prefer).length);
      if (i >= 0) put("place", texts[i], false, [i]);
    }
    if (!fields.apply) {
      let i = texts.findIndex((t) => URL_RE.test(t));
      if (i < 0) i = texts.findIndex((t) => APPLY_HINT.test(t) && !matchLabel(t));
      if (i >= 0) put("apply", texts[i], false, [i]);
    }
    if (!fields.title && lines.length) {
      const tl = guessTitle(doc, ref, prefer);
      if (tl.length) put("title", tl.map((l) => l.text.trim()).join(" "), false, tl.map((t) => lines.indexOf(t)));
    }
    return fields;
  }

  // ------------------------------------------------------------ 검증
  const CONFUSABLE = /\d[OoIl|SsBZ]|[OoIl|SsBZ]\d/;
  function verify(result, threshold = 60) {
    const out = [];
    const owner = new Map();
    for (const [name, f] of Object.entries(result.fields)) f.words.forEach((w) => owner.set(w, name));
    for (const [name, f] of Object.entries(result.fields)) {
      for (const r of f.dates) {
        if (r.certain) continue;
        out.push({ kind: "ambiguous_date", text: r.raw, message: `${FIELD_NAMES[name]}의 '${r.raw}': ${r.reason}`,
          options: r.options.map(formatDate), fieldName: name, reading: r, resolved: false });
      }
    }
    const seen = new Set();
    for (const w of result.doc.words) {
      const low = w.conf < threshold;
      const conf = CONFUSABLE.test(w.text) && w.conf < 90;
      if (!(low || conf) || seen.has(w)) continue;
      seen.add(w);
      const why = low ? `확신도 ${Math.round(w.conf)}%` : "숫자와 비슷한 글자가 섞여 있음";
      out.push({ kind: "low_conf", text: w.text, message: `'${w.text}' 글자가 확실하지 않습니다 (${why}).`,
        fieldName: owner.get(w) || null, word: w, resolved: false });
    }
    for (const u of out) if (u.fieldName && result.fields[u.fieldName]) result.fields[u.fieldName].uncertain = true;
    return out;
  }

  function applyDateChoice(f, reading, choice) {
    reading.chosen = reading.options[choice];
    reading.certain = true;
    reading.reason = "사용자가 선택";
    f.value = describe(f.raw, f.dates) || f.value;
  }

  // ------------------------------------------------------------ 피드백 (이 기기 브라우저에 저장)
  const FB_KEY = "eye.feedback.v1";
  class Feedback {
    constructor(storage) {
      this.storage = storage;
      this.data = { dateOrder: { MD: 0, DM: 0 }, corrections: {}, flagStats: { confirmed: 0, corrected: 0 } };
      try { const s = storage && storage.getItem(FB_KEY); if (s) Object.assign(this.data, JSON.parse(s)); } catch (e) { /* 저장소 없음 */ }
    }
    save() { try { this.storage && this.storage.setItem(FB_KEY, JSON.stringify(this.data)); } catch (e) { /* 무시 */ } }
    get datePreference() { const { MD = 0, DM = 0 } = this.data.dateOrder; return DM >= 2 && DM > MD ? "DM" : "MD"; }
    get confThreshold() {
      const { confirmed: c = 0, corrected: k = 0 } = this.data.flagStats;
      if (c + k < 5) return 60;
      return Math.max(40, Math.min(80, 60 + (k / (c + k) - 0.5) * 40));
    }
    applyCorrections(words) {
      let n = 0;
      for (const w of words) {
        const fix = this.data.corrections[w.text];
        if (fix) { w.text = fix; w.conf = Math.max(w.conf, 95); n++; }
      }
      return n;
    }
    recordDate(order) { this.data.dateOrder[order] = (this.data.dateOrder[order] || 0) + 1; this.save(); }
    recordWord(original, fixed) {
      if (fixed && fixed !== original) { this.data.corrections[original] = fixed; this.data.flagStats.corrected++; }
      else this.data.flagStats.confirmed++;
      this.save();
    }
    reset() { try { this.storage && this.storage.removeItem(FB_KEY); } catch (e) { /* 무시 */ }
      this.data = { dateOrder: { MD: 0, DM: 0 }, corrections: {}, flagStats: { confirmed: 0, corrected: 0 } }; }
  }

  // ------------------------------------------------------------ 결과 만들기
  function analyze(doc, fb, { ref = new Date(), extractInfo = true } = {}) {
    const result = { doc, fields: {}, uncertainties: [], notices: [] };
    if (extractInfo) result.fields = extract(doc, ref, fb.datePreference);
    result.uncertainties = verify(result, fb.confThreshold);
    return result;
  }

  function summaryLines(result) {
    const out = [];
    for (const [k, label] of Object.entries(FIELD_NAMES)) {
      const f = result.fields[k];
      if (!f) continue;
      const mark = f.uncertain && !f.value.includes("확실하지 않음") ? " (확실하지 않음)" : "";
      out.push(`${label}: ${f.value}${mark}`);
    }
    if (!out.length) out.push("행사 정보를 찾지 못했습니다. 전체 읽기를 선택하세요.");
    const n = result.uncertainties.filter((u) => !u.resolved).length;
    if (n) out.push(`확실하지 않은 항목이 ${n}개 있습니다.`);
    return out;
  }

  /** 읽는 순서대로 블록을 말하기용 문장으로 만든다. */
  function spokenBlocks(result) {
    const ids = new Set(result.uncertainties.filter((u) => u.kind === "low_conf" && !u.resolved).map((u) => u.word));
    const fmt = (w) => ids.has(w) ? `(확실하지 않은 글자, ${w.text})` : w.text;
    const out = [];
    result.doc.pages.forEach((p, i) => {
      if (result.doc.pages.length > 1) out.push(`${i + 1}쪽`);
      for (const b of p.blocks) {
        if (b.kind === "table") {
          const rows = tableRows(b);
          out.push(`표 시작, ${rows.length}행 ${Math.max(...rows.map((r) => r.length))}열`);
          rows.forEach((r, k) => out.push(`${k + 1}행, ` + r.map((l) => l.render(fmt)).join(", ")));
          out.push("표 끝");
        } else if (b.kind === "heading") out.push("제목, " + b.lines.map((l) => l.render(fmt)).join(" "));
        else if (b.kind === "list") b.lines.forEach((l) => out.push("목록, " + l.render(fmt)));
        else out.push(b.lines.map((l) => l.render(fmt)).join(" "));
      }
    });
    return out;
  }

  function plainText(result) {
    const ids = new Set(result.uncertainties.filter((u) => u.kind === "low_conf" && !u.resolved).map((u) => u.word));
    const fmt = (w) => ids.has(w) ? `[?${w.text}]` : w.text;
    const parts = [];
    result.doc.pages.forEach((p, i) => {
      if (result.doc.pages.length > 1) parts.push(`--- ${i + 1}쪽 ---`);
      for (const b of p.blocks) {
        if (b.kind === "table") parts.push("[표]\n" + tableRows(b).map((r, k) => `${k + 1}행: ` + r.map((l) => l.render(fmt)).join(" | ")).join("\n"));
        else if (b.kind === "heading") parts.push("# " + b.lines.map((l) => l.render(fmt)).join(" "));
        else if (b.kind === "list") parts.push(b.lines.map((l) => l.render(fmt)).join("\n"));
        else parts.push(b.lines.map((l) => l.render(fmt)).join(" "));
      }
    });
    return parts.join("\n\n");
  }

  root.Eye = {
    Word, Line, Block, Doc, Feedback, FIELD_NAMES,
    findDates, findTimes, formatDate, formatTime, iso, weekday,
    groupLines, groupBlocks, readingOrder, findTables, tableRows, buildPage, stripHeadersFooters,
    extract, describe, verify, applyDateChoice, analyze, summaryLines, spokenBlocks, plainText,
  };
})(typeof window !== "undefined" ? window : globalThis);
