/* Eye 모바일 화면: 사진·캡처·PDF 입력 → 기기 안에서 OCR → 핵심 정보 음성 안내. */
(function () {
  "use strict";
  const E = window.Eye;
  const $ = (s) => document.querySelector(s);
  const abs = (p) => new URL(p, location.href).href;
  document.documentElement.lang = "ko";

  let storage = null;
  try { storage = window.localStorage; storage.getItem("x"); } catch (e) { storage = null; }
  const fb = new E.Feedback(storage);

  const state = { result: null, isExample: true, sourceUrl: "", readQueue: [], readIndex: 0 };

  // ------------------------------------------------------------ 진행 단계
  const STEPS = ["감지", "전처리", "글자 인식", "읽는 순서", "정보 추출", "검증", "출력"];
  function renderSteps(active = -1, done = -1) {
    $("#steps").innerHTML = STEPS.map((s, i) => {
      const st = i <= done ? "done" : i === active ? "active" : "";
      return `<li class="${st}"><span class="num">${"①②③④⑤⑥⑦"[i]}</span>${s}</li>`;
    }).join("");
  }
  function status(msg) { $("#status").textContent = msg; }

  // ------------------------------------------------------------ 음성
  const synth = window.speechSynthesis;
  let koVoice = null;
  function pickVoice() {
    if (!synth) return;
    const vs = synth.getVoices();
    koVoice = vs.find((v) => /^ko/i.test(v.lang)) || null;
  }
  if (synth) { pickVoice(); synth.onvoiceschanged = pickVoice; }
  function speak(lines, { onEach } = {}) {
    stopSpeaking();
    if (!synth) { status("이 브라우저는 음성 읽기를 지원하지 않습니다. 화면낭독기로 아래 글을 읽어 주세요."); return; }
    const rate = +$("#rate").value;
    lines.forEach((text, i) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ko-KR"; u.rate = rate;
      if (koVoice) u.voice = koVoice;
      if (onEach) u.onstart = () => onEach(i);
      synth.speak(u);
    });
  }
  function stopSpeaking() { if (synth) synth.cancel(); }

  // ------------------------------------------------------------ ② 전처리 (캔버스)
  function prepare(src, sw, sh, fixSkew = false) {
    let scale = sw < 1800 ? Math.min(3, 1800 / sw) : 1;
    const maxSide = 3200;
    if (Math.max(sw, sh) * scale > maxSide) scale = maxSide / Math.max(sw, sh);
    const W = Math.round(sw * scale), H = Math.round(sh * scale);
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingQuality = "high";
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    g.drawImage(src, 0, 0, W, H);
    const img = g.getImageData(0, 0, W, H);
    const d = img.data;
    const gray = new Uint8ClampedArray(W * H);
    for (let i = 0, j = 0; i < d.length; i += 4, j++) gray[j] = (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
    // 어두운 배경(카드뉴스)이면 뒤집기
    const edge = [];
    for (let x = 0; x < W; x += 4) { edge.push(gray[x], gray[(H - 1) * W + x]); }
    for (let y = 0; y < H; y += 4) { edge.push(gray[y * W], gray[y * W + W - 1]); }
    edge.sort((a, b) => a - b);
    if (edge[edge.length >> 1] < 110) for (let j = 0; j < gray.length; j++) gray[j] = 255 - gray[j];
    for (let i = 0, j = 0; i < d.length; i += 4, j++) { d[i] = d[i + 1] = d[i + 2] = gray[j]; }
    g.putImageData(img, 0, 0);
    // 그림자·배경 장식 줄이기: 크게 흐린 배경으로 나누기 (작게 줄였다 키우는 방식)
    const sm = document.createElement("canvas");
    sm.width = Math.max(8, W >> 5); sm.height = Math.max(8, H >> 5);
    const sg = sm.getContext("2d");
    sg.imageSmoothingQuality = "high";
    sg.drawImage(c, 0, 0, sm.width, sm.height);
    const bg = document.createElement("canvas");
    bg.width = W; bg.height = H;
    const bgc = bg.getContext("2d", { willReadFrequently: true });
    bgc.imageSmoothingQuality = "high";
    bgc.drawImage(sm, 0, 0, W, H);
    const b = bgc.getImageData(0, 0, W, H).data;
    const hist = new Uint32Array(256);
    for (let j = 0; j < gray.length; j++) {
      const v = Math.min(255, (gray[j] / (b[j * 4] + 1)) * 255);
      gray[j] = v; hist[gray[j]]++;
    }
    // 대비 보정 (아래위 1% 잘라 늘리기)
    const cut = gray.length * 0.01;
    let lo = 0, hi = 255, acc = 0;
    while (lo < 255 && (acc += hist[lo]) < cut) lo++;
    acc = 0;
    while (hi > 0 && (acc += hist[hi]) < cut) hi--;
    const span = Math.max(1, hi - lo);
    for (let i = 0, j = 0; i < d.length; i += 4, j++) {
      const v = Math.max(0, Math.min(255, ((gray[j] - lo) * 255) / span));
      d[i] = d[i + 1] = d[i + 2] = v;
    }
    g.putImageData(img, 0, 0);
    return { canvas: fixSkew ? deskew(c) : c, scale };
  }

  // 기울기 보정: 글자 점들을 돌려 가며 가로줄이 가장 또렷해지는 각도를 찾는다
  function estimateSkew(c) {
    const k = 700 / Math.max(c.width, c.height);
    const w = Math.round(c.width * k), h = Math.round(c.height * k);
    const t = document.createElement("canvas");
    t.width = w; t.height = h;
    const tg = t.getContext("2d", { willReadFrequently: true });
    tg.drawImage(c, 0, 0, w, h);
    const d = tg.getImageData(0, 0, w, h).data;
    const xs = [], ys = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (d[(y * w + x) * 4] < 128) { xs.push(x - w / 2); ys.push(y - h / 2); }
    }
    if (xs.length < 50) return 0;
    const diag = Math.ceil(Math.hypot(w, h));
    let best = 0, bestScore = -1;
    for (let deg = -6; deg <= 6.001; deg += 0.25) {
      const a = (deg * Math.PI) / 180, sn = Math.sin(a), cs = Math.cos(a);
      const rows = new Float64Array(diag);
      for (let i = 0; i < xs.length; i++) rows[Math.round(xs[i] * sn + ys[i] * cs + diag / 2)]++;
      let sum = 0, sq = 0;
      for (const v of rows) { sum += v; sq += v * v; }
      const score = sq / diag - (sum / diag) ** 2;
      if (score > bestScore) { bestScore = score; best = deg; }
    }
    return best;
  }

  function deskew(c) {
    const deg = estimateSkew(c);
    if (Math.abs(deg) < 0.25) return c;
    const out = document.createElement("canvas");
    out.width = c.width; out.height = c.height;
    const g = out.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, out.width, out.height);
    g.translate(out.width / 2, out.height / 2);
    g.rotate((deg * Math.PI) / 180);
    g.drawImage(c, -c.width / 2, -c.height / 2);
    return out;
  }

  // ------------------------------------------------------------ ③ OCR (Tesseract.js, 기기 안에서)
  let workerPromise = null;
  function getWorker() {
    if (!workerPromise) {
      workerPromise = Tesseract.createWorker("kor+eng", 1, {
        workerPath: abs("eye-worker.js"),
        corePath: abs("vendor/core"),
        langPath: abs("tessdata"),
        workerBlobURL: false,
        gzip: true,
        cacheMethod: "none",
        logger: (m) => {
          if (m.status === "recognizing text") status(`글자를 읽는 중… ${Math.round(m.progress * 100)}%`);
          else if (/loading/.test(m.status)) status(`인식 엔진 준비 중… (처음 한 번은 몇 초 걸립니다)`);
        },
      }).catch((e) => { workerPromise = null; throw e; });
    }
    return workerPromise;
  }

  async function recognize(canvas, scale, psm, page) {
    const worker = await getWorker();
    await worker.setParameters({ tessedit_pageseg_mode: String(psm), preserve_interword_spaces: "1", user_defined_dpi: psm === 3 ? "216" : "0" });
    const { data } = await worker.recognize(canvas, {}, { blocks: true, text: false, hocr: false, tsv: false });
    let words = data.words;
    if (!words || !words.length) {
      words = [];
      for (const bl of data.blocks || []) for (const p of bl.paragraphs || []) for (const l of p.lines || []) words.push(...(l.words || []));
    }
    const out = [];
    for (const w of words) {
      const t = (w.text || "").trim();
      if (!t || w.confidence < 0) continue;
      const bb = w.bbox;
      out.push(new E.Word(t, bb.x0 / scale, bb.y0 / scale, (bb.x1 - bb.x0) / scale, (bb.y1 - bb.y0) / scale, w.confidence, page, true));
    }
    fb.applyCorrections(out);
    return out;
  }

  // ------------------------------------------------------------ 입력 처리
  function loadImage(blob) {
    return new Promise((res, rej) => {
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => res({ img, url });
      img.onerror = () => { URL.revokeObjectURL(url); rej(new Error("이미지를 열 수 없습니다. JPG나 PNG로 다시 시도해 주세요.")); };
      img.src = url;
    });
  }

  async function runImage(blob, name) {
    renderSteps(0);
    status("이미지를 여는 중…");
    const { img, url } = await loadImage(blob);
    $("#preview").src = url;
    $("#preview").hidden = false;
    renderSteps(1, 0);
    status("이미지를 보정하는 중…");
    await tick();
    const { canvas, scale } = prepare(img, img.naturalWidth, img.naturalHeight);
    renderSteps(2, 1);
    const words = await recognize(canvas, scale, 11, 0);
    renderSteps(3, 2);
    const page = E.buildPage(words, img.naturalWidth, img.naturalHeight);
    const doc = new E.Doc(name, "image", [page]);
    renderSteps(4, 3);
    const result = E.analyze(doc, fb);
    renderSteps(6, 5);
    if (!words.length) result.notices.push("이 이미지에서 글자를 찾지 못했습니다.");
    show(result, false);
    renderSteps(-1, 6);
  }

  async function runPdf(file) {
    renderSteps(0);
    status("PDF를 여는 중…");
    const pdfjs = window.pdfjsLib;
    pdfjs.GlobalWorkerOptions.workerSrc = abs("vendor/pdf.worker.min.js");
    const pdf = await pdfjs.getDocument({
      data: await file.arrayBuffer(), cMapUrl: abs("cmaps/"), cMapPacked: true,
      CMapReaderFactory: CMapFactory, useWorkerFetch: false,
    }).promise;
    const pages = [];
    let scannedPages = 0;
    for (let n = 1; n <= pdf.numPages; n++) {
      const pg = await pdf.getPage(n);
      const vp = pg.getViewport({ scale: 1 });
      const tc = await pg.getTextContent();
      const chars = tc.items.reduce((s, it) => s + (it.str || "").trim().length, 0);
      if (chars >= 30) {
        renderSteps(3, 0);
        status(`${n}/${pdf.numPages}쪽: 글자 정보를 읽는 중…`);
        pages.push(E.buildPage(textItemsToWords(tc.items, vp, n - 1), vp.width, vp.height));
        continue;
      }
      scannedPages++;
      renderSteps(1, 0);
      status(`${n}/${pdf.numPages}쪽: 스캔본이라 이미지로 바꾸는 중…`);
      const s = Math.min(3, 2000 / vp.width);
      const v2 = pg.getViewport({ scale: s });
      const c = document.createElement("canvas");
      c.width = Math.round(v2.width); c.height = Math.round(v2.height);
      await pg.render({ canvasContext: c.getContext("2d"), viewport: v2, background: "#fff" }).promise;
      const { canvas, scale } = prepare(c, c.width, c.height, true);
      renderSteps(2, 1);
      const words = await recognize(canvas, scale * s, 3, n - 1);
      pages.push(E.buildPage(words, vp.width, vp.height));
    }
    renderSteps(4, 3);
    E.stripHeadersFooters(pages);
    const doc = new E.Doc(file.name, "pdf", pages, scannedPages > pdf.numPages / 2);
    const result = E.analyze(doc, fb, { extractInfo: false });
    if (scannedPages) result.notices.push(scannedPages === pdf.numPages
      ? "스캔본입니다. 글자 정보가 없어 글자 인식(OCR)으로 읽었습니다."
      : `${scannedPages}쪽이 스캔본이라 글자 인식(OCR)으로 읽었습니다.`);
    renderSteps(6, 5);
    show(result, false);
    renderSteps(-1, 6);
  }

  // 한글 PDF 글꼴 표(cmap)를 배포 가능한 확장자(.bcmap.wasm)로 불러온다
  class CMapFactory {
    constructor({ baseUrl }) { this.baseUrl = baseUrl; }
    async fetch({ name }) {
      const res = await fetch(`${this.baseUrl}${name}.bcmap.wasm`);
      if (!res.ok) throw new Error(`글꼴 표 ${name}을(를) 찾을 수 없습니다.`);
      return { cMapData: new Uint8Array(await res.arrayBuffer()), compressionType: 1 };
    }
  }

  function textItemsToWords(items, vp, page) {
    const out = [];
    for (const it of items) {
      const str = it.str || "";
      if (!str.trim()) continue;
      const tx = pdfjsLib.Util.transform(vp.transform, it.transform);
      const h = Math.hypot(tx[2], tx[3]) || 10;
      const total = (it.width || str.length * h * 0.5) * vp.scale;
      const x0 = tx[4], top = tx[5] - h;
      // 띄어쓰기 단위로 나누고, 글자 수 비율로 폭을 나눈다
      let pos = 0;
      for (const part of str.split(/(\s+)/)) {
        const w = (part.length / str.length) * total;
        if (part.trim()) out.push(new E.Word(part, x0 + pos, top, w, h, 100, page, false));
        pos += w;
      }
    }
    return out;
  }

  const tick = () => new Promise((r) => setTimeout(r, 30));

  async function handleFile(file) {
    if (!file) return;
    stopSpeaking();
    $("#result").setAttribute("aria-busy", "true");
    try {
      if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) await runPdf(file);
      else await runImage(file, file.name || "붙여넣은 이미지");
    } catch (e) {
      console.error(e);
      status(`읽지 못했습니다: ${e.message || e}`);
      renderSteps(-1, -1);
    } finally {
      $("#result").removeAttribute("aria-busy");
    }
  }

  // ------------------------------------------------------------ ⑦ 출력 (화면)
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function show(result, isExample) {
    state.result = result;
    state.isExample = isExample;
    $("#example-badge").hidden = !isExample;
    $("#notices").innerHTML = result.notices.map((n) => `<p class="notice">${esc(n)}</p>`).join("");
    renderFields();
    renderUncertain();
    renderFull();
    renderLearning();
    const isPdf = result.doc.kind === "pdf";
    $("#key-wrap").hidden = isPdf;
    $("#btn-key").hidden = isPdf;
    if (!isExample) {
      status(isPdf ? `${result.doc.pages.length}쪽 문서를 읽었습니다.` : "다 읽었습니다. 핵심 정보를 읽어 드립니다.");
      if (!isPdf && $("#autoread").checked) speak(E.summaryLines(result));
      $("#result").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      $("#result-title").focus({ preventScroll: true });
    }
  }

  function renderFields() {
    const r = state.result;
    const rows = Object.entries(E.FIELD_NAMES).map(([k, label]) => {
      const f = r.fields[k];
      if (!f) return `<div class="field missing"><dt>${label}</dt><dd>찾지 못함</dd></div>`;
      const chip = f.uncertain ? `<span class="chip">확실하지 않음</span>` : "";
      return `<div class="field${f.uncertain ? " unsure" : ""}"><dt>${label}</dt><dd>${esc(f.value.replace(" (확실하지 않음)", ""))} ${chip}</dd></div>`;
    });
    $("#fields").innerHTML = rows.join("");
    const urlLink = $("#open-original");
    const u = state.sourceUrl.trim();
    if (u && /^https?:\/\//i.test(u)) { urlLink.href = u; urlLink.hidden = false; } else urlLink.hidden = true;
  }

  function renderUncertain() {
    const r = state.result;
    const pending = r.uncertainties.filter((u) => !u.resolved);
    $("#unsure-count").textContent = pending.length ? `${pending.length}개` : "없음";
    const list = $("#unsure");
    if (!pending.length) { list.innerHTML = `<li class="empty">확인할 항목이 없습니다.</li>`; return; }
    list.innerHTML = "";
    pending.forEach((u) => {
      const li = document.createElement("li");
      li.className = "unsure-item";
      li.innerHTML = `<p>${esc(u.message)}</p>`;
      const row = document.createElement("div");
      row.className = "choice-row";
      if (u.kind === "ambiguous_date") {
        u.options.forEach((opt, i) => {
          const b = document.createElement("button");
          b.type = "button"; b.className = "btn choice"; b.textContent = opt;
          b.onclick = () => {
            const f = r.fields[u.fieldName];
            const picked = u.reading.options[i];
            const first = parseInt(u.reading.raw, 10);
            E.applyDateChoice(f, u.reading, i);
            if (!state.isExample) fb.recordDate(picked.getMonth() + 1 === first ? "MD" : "DM");
            u.resolved = true;
            refreshAfterFix(`${opt}(으)로 정했습니다.`);
          };
          row.appendChild(b);
        });
      } else {
        const id = "fix-" + Math.random().toString(36).slice(2, 8);
        row.innerHTML = `<label class="sr-only" for="${id}">바른 글자</label><input id="${id}" class="fix" value="${esc(u.text)}" autocomplete="off">`;
        const ok = document.createElement("button");
        ok.type = "button"; ok.className = "btn"; ok.textContent = "저장";
        ok.onclick = () => {
          const v = row.querySelector("input").value.trim();
          if (!state.isExample) fb.recordWord(u.text, v);
          if (v && v !== u.text) {
            for (const f of Object.values(r.fields)) { f.value = f.value.split(u.text).join(v); f.raw = f.raw.split(u.text).join(v); }
            u.word.text = v;
          }
          u.resolved = true;
          refreshAfterFix(v && v !== u.text ? `'${v}'(으)로 고쳤습니다. 다음부터 자동으로 고칩니다.` : "맞다고 기록했습니다.");
        };
        row.appendChild(ok);
      }
      li.appendChild(row);
      list.appendChild(li);
    });
  }

  function refreshAfterFix(msg) {
    const r = state.result;
    for (const f of Object.values(r.fields)) {
      f.uncertain = r.uncertainties.some((u) => !u.resolved && u.fieldName === f.name) || f.dates.some((d) => !d.certain);
    }
    renderFields(); renderUncertain(); renderFull(); renderLearning();
    status(msg);
  }

  function renderFull() {
    const r = state.result;
    const ids = new Set(r.uncertainties.filter((u) => u.kind === "low_conf" && !u.resolved).map((u) => u.word));
    const fmt = (w) => ids.has(w) ? `<mark class="unsure-word" title="확실하지 않음">${esc(w.text)}</mark>` : esc(w.text);
    const parts = [];
    r.doc.pages.forEach((p, i) => {
      if (r.doc.pages.length > 1) parts.push(`<p class="page-no">${i + 1}쪽</p>`);
      for (const b of p.blocks) {
        if (b.kind === "table") {
          const rows = E.tableRows(b);
          parts.push(`<div class="table-wrap"><table>${rows.map((row, k) =>
            `<tr>${row.map((l) => k === 0 ? `<th scope="col">${l.render(fmt)}</th>` : `<td>${l.render(fmt)}</td>`).join("")}</tr>`).join("")}</table></div>`);
        } else if (b.kind === "heading") parts.push(`<h4>${b.lines.map((l) => l.render(fmt)).join(" ")}</h4>`);
        else if (b.kind === "list") parts.push(`<ul>${b.lines.map((l) => `<li>${l.render(fmt)}</li>`).join("")}</ul>`);
        else parts.push(`<p>${b.lines.map((l) => l.render(fmt)).join(" ")}</p>`);
      }
    });
    $("#full").innerHTML = parts.join("") || "<p>읽은 글이 없습니다.</p>";
    state.readQueue = E.spokenBlocks(r);
    state.readIndex = 0;
    updateReader();
  }

  function updateReader() {
    const n = state.readQueue.length;
    $("#reader-pos").textContent = n ? `${Math.min(state.readIndex + 1, n)} / ${n}` : "0 / 0";
  }
  function readFrom(i) {
    if (!state.readQueue.length) return;
    state.readIndex = Math.max(0, Math.min(i, state.readQueue.length - 1));
    updateReader();
    const start = state.readIndex;
    speak(state.readQueue.slice(start), { onEach: (k) => { state.readIndex = start + k; updateReader(); } });
  }

  function renderLearning() {
    const d = fb.data;
    const fixes = Object.entries(d.corrections);
    $("#learn").innerHTML = `
      <div class="field"><dt>날짜 읽는 순서</dt><dd>${fb.datePreference === "MD" ? "월/일" : "일/월"} <span class="muted">(월/일 ${d.dateOrder.MD || 0}회 · 일/월 ${d.dateOrder.DM || 0}회 선택)</span></dd></div>
      <div class="field"><dt>불확실 기준</dt><dd>확신도 ${Math.round(fb.confThreshold)}% 미만</dd></div>
      <div class="field"><dt>자동으로 고치는 글자</dt><dd>${fixes.length ? fixes.map(([a, b]) => `${esc(a)} → ${esc(b)}`).join("<br>") : "없음"}</dd></div>
      ${storage ? "" : `<p class="muted">이 화면에서는 기록을 저장할 수 없어 창을 닫으면 사라집니다.</p>`}`;
  }

  // ------------------------------------------------------------ 예시 (처음 화면)
  function exampleDoc() {
    const rows = [["2026 진로 특강", 80, 140, 96], ["AI 시대의 커리어 설계", 80, 260, 56], ["일시: 12/03(목) 14:00~16:00", 80, 460, 48],
      ["장소: 학생회관 3층 대강당", 80, 570, 48], ["신청 방법: 구글폼 forms.gle/abc123", 80, 680, 48], ["신청 마감: 11/30(월)까지", 80, 790, 48],
      ["주최: 학생처 진로지원센터", 80, 1180, 36]];
    const words = [];
    for (const [text, x, y, h] of rows) {
      let cx = x;
      for (const t of text.split(" ")) {
        words.push(new E.Word(t, cx, y, t.length * h * 0.8, h, t === "구글폼" ? 41 : 93, 0, true));
        cx += t.length * h * 0.8 + h * 0.45;
      }
    }
    return new E.Doc("예시 포스터", "image", [E.buildPage(words, 1080, 1350)]);
  }

  async function runSample() {
    const res = await fetch("sample.jpg");
    if (!res.ok) throw new Error("예시 이미지를 불러오지 못했습니다.");
    await handleFile(new File([await res.blob()], "예시 포스터.jpg", { type: "image/jpeg" }));
  }

  // ------------------------------------------------------------ 연결
  $("#file").addEventListener("change", (e) => { handleFile(e.target.files[0]); e.target.value = ""; });
  $("#btn-sample").addEventListener("click", () => runSample().catch((e) => status(e.message)));
  $("#source-url").addEventListener("input", (e) => { state.sourceUrl = e.target.value; if (state.result) renderFields(); });
  document.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/") || i.type === "application/pdf");
    if (item) { e.preventDefault(); handleFile(item.getAsFile()); }
  });
  const drop = $("#dropzone");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); handleFile(e.dataTransfer.files[0]); });

  $("#btn-key").addEventListener("click", () => state.result && speak(E.summaryLines(state.result)));
  $("#btn-all").addEventListener("click", () => readFrom(0));
  $("#btn-stop").addEventListener("click", stopSpeaking);
  $("#btn-prev").addEventListener("click", () => readFrom(state.readIndex - 1));
  $("#btn-next").addEventListener("click", () => readFrom(state.readIndex + 1));
  $("#btn-copy").addEventListener("click", () => {
    const text = (state.result.doc.kind === "image" ? E.summaryLines(state.result).join("\n") + "\n\n" : "") + E.plainText(state.result);
    navigator.clipboard.writeText(text).then(() => status("전체 글을 복사했습니다."), () => {
      const sel = getSelection(); const range = document.createRange();
      range.selectNodeContents($("#full")); sel.removeAllRanges(); sel.addRange(range);
      status("복사가 막혀 있어 글을 선택해 두었습니다. 길게 눌러 복사하세요.");
    });
  });
  $("#btn-reset").addEventListener("click", () => { $("#reset-confirm").hidden = false; $("#btn-reset-yes").focus(); });
  $("#btn-reset-no").addEventListener("click", () => { $("#reset-confirm").hidden = true; });
  $("#btn-reset-yes").addEventListener("click", () => { fb.reset(); $("#reset-confirm").hidden = true; renderLearning(); status("학습 기록을 지웠습니다."); });
  const rate = $("#rate");
  rate.addEventListener("input", () => { $("#rate-val").textContent = (+rate.value).toFixed(1) + "배"; });

  window.__eyeDebug = { prepare };
  renderSteps(-1, -1);
  show(E.analyze(exampleDoc(), fb), true);
  status("사진이나 캡처, PDF를 고르면 읽기 시작합니다.");
})();
