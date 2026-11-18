// node --test web/tests  — 파이썬 tests/test_logic.py 와 같은 내용을 웹 로직으로 확인한다.
const test = require("node:test");
const assert = require("node:assert/strict");
require("../eye.js");
const E = globalThis.Eye;
const REF = new Date(2026, 10, 18);
const ymd = (d) => E.iso(d);

function docFromRows(rows, h = 20) {
  const words = [];
  for (const [text, x, y, hh = h] of rows) {
    let cx = x;
    for (const t of text.split(/\s+/)) {
      words.push(new E.Word(t, cx, y, t.length * hh * 0.9, hh, 95, 0, false));
      cx += t.length * hh * 0.9 + hh * 0.5;
    }
  }
  return new E.Doc("test", "image", [E.buildPage(words, 1000, 1400)]);
}
const memStore = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }; };

test("dates", () => {
  let r = E.findDates("2026.12.3(목) 오후 2시", REF)[0];
  assert.equal(ymd(r.chosen), "2026-12-03"); assert.ok(r.certain);
  r = E.findDates("12/03", REF)[0];
  assert.ok(!r.certain); assert.deepEqual(r.options.map(ymd), ["2026-12-03", "2027-03-12"]);
  r = E.findDates("3/12(목)", REF)[0];
  assert.ok(r.certain); assert.equal(ymd(r.chosen), "2026-12-03");
  r = E.findDates("12월 3일(수)", REF)[0];
  assert.ok(!r.certain);
  assert.equal(ymd(E.findDates("12/03", REF, "DM")[0].chosen), "2027-03-12");
  assert.equal(ymd(E.findDates("25/12", REF)[0].chosen), "2026-12-25");
  assert.deepEqual(E.findDates("평점 4.5점", REF), []);
  assert.deepEqual(E.findTimes("14:00~16:00"), ["14:00", "16:00"]);
  assert.deepEqual(E.findTimes("오후 2시 30분"), ["14:30"]);
  assert.deepEqual(E.findTimes("오전 10시 반"), ["10:30"]);
  assert.deepEqual(E.findTimes("3시간 동안"), []);
  assert.equal(E.formatDate(new Date(2026, 11, 3)), "2026년 12월 3일 목요일");
});

test("layout", () => {
  const W = (t, x, y, w) => new E.Word(t, x, y, w ?? t.length * 18, 20, 95);
  assert.deepEqual(E.groupLines([W("왼쪽", 0, 0), W("단", 50, 0), W("오른쪽", 500, 0)]).map((l) => l.text), ["왼쪽 단", "오른쪽"]);
  const rows = [["제목입니다", 0, 0, 40]];
  for (let i = 0; i < 4; i++) rows.push([`왼쪽 단의 ${i}번째 줄은 이렇게 길게 이어집니다`, 0, 100 + i * 30]);
  for (let i = 0; i < 4; i++) rows.push([`오른쪽 단의 ${i}번째 줄도 길게 이어집니다`, 600, 100 + i * 30]);
  const d = docFromRows(rows);
  assert.equal(d.blocks[0].kind, "heading");
  assert.ok(d.blocks[1].text.startsWith("왼쪽 단의 0") && !d.blocks[1].text.includes("오른쪽"));
  const t = docFromRows([["이름", 0, 0], ["학번", 300, 0], ["학과", 600, 0], ["홍길동", 0, 40], ["2026001", 300, 40], ["컴퓨터", 600, 40], ["김철수", 0, 80], ["2026002", 300, 80], ["전자", 600, 80]]);
  const tb = t.blocks.filter((b) => b.kind === "table");
  assert.equal(tb.length, 1); assert.deepEqual(tb[0].rows[1], ["홍길동", "2026001", "컴퓨터"]);
  assert.deepEqual(docFromRows([["설명 문단입니다", 0, 0], ["1. 첫째", 0, 30], ["2. 둘째", 0, 60]]).blocks.map((b) => b.kind), ["paragraph", "list"]);
  const ko = [W("학", 0, 0, 20), W("생", 22, 0, 20), W("회", 44, 0, 20), W("관", 66, 0, 20), W("3층", 100, 0, 40)];
  assert.equal(E.groupLines(ko)[0].text, "학생회관 3층");
  const pages = [1, 2, 3].map((n) => E.buildPage([new E.Word("강의자료", 0, 5, 80, 20, 100, 0, false), new E.Word(`본문${n}`, 0, 500, 60, 20, 100, 0, false), new E.Word(`- ${n} -`, 400, 1370, 40, 20, 100, 0, false)], 1000, 1400));
  E.stripHeadersFooters(pages);
  assert.deepEqual(pages.map((p) => p.blocks.map((b) => b.text)), [["본문1"], ["본문2"], ["본문3"]]);
});

test("extract + verify + feedback", () => {
  const poster = docFromRows([["2026 진로 특강", 50, 50, 60], ["일시: 12/03(목) 14:00~16:00", 50, 200], ["장소: 학생회관 3층 대강당", 50, 250], ["신청 방법: 구글폼 forms.gle/abc123", 50, 300], ["신청 마감: 11/30(월)까지", 50, 350]]);
  const f = E.extract(poster, REF);
  assert.equal(f.title.value, "2026 진로 특강");
  assert.equal(f.datetime.value, "2026년 12월 3일 목요일 오후 2시부터 오후 4시까지");
  assert.equal(f.place.value, "학생회관 3층 대강당");
  assert.ok(f.apply.value.includes("forms.gle/abc123"));
  assert.equal(f.deadline.value, "2026년 11월 30일 월요일");
  const un = E.extract(docFromRows([["코딩 동아리 신입 모집", 50, 50, 50], ["12월 10일(목) 오후 7시", 50, 200], ["공학관 101호", 50, 250], ["11월 30일(월)까지 신청", 50, 300], ["bit.ly/code-club", 50, 350]]), REF);
  assert.equal(un.title.value, "코딩 동아리 신입 모집"); assert.equal(un.place.value, "공학관 101호");
  assert.equal(un.deadline.value, "2026년 11월 30일 월요일"); assert.ok(un.datetime.value.startsWith("2026년 12월 10일"));

  const fb = new E.Feedback(memStore());
  const res = E.analyze(docFromRows([["행사명: 송년회", 0, 0], ["일시: 12/03 18:00", 0, 40]]), fb, { ref: REF });
  const amb = res.uncertainties.filter((u) => u.kind === "ambiguous_date");
  assert.equal(amb.length, 1);
  E.applyDateChoice(res.fields.datetime, amb[0].reading, 1);
  assert.equal(res.fields.datetime.value, "2027년 3월 12일 금요일 오후 6시");

  const d2 = docFromRows([["장소: 공학관", 0, 0]]); d2.words.at(-1).conf = 30;
  const r2 = E.analyze(d2, fb, { ref: REF });
  assert.equal(r2.uncertainties[0].fieldName, "place");
  assert.ok(E.plainText(r2).includes("[?공학관]"));

  const store = memStore();
  const fb2 = new E.Feedback(store);
  fb2.recordWord("몽사활동", "봉사활동");
  const words = [new E.Word("몽사활동", 0, 0, 10, 10, 40)];
  assert.equal(new E.Feedback(store).applyCorrections(words), 1);
  assert.equal(words[0].text, "봉사활동");
  fb2.recordDate("DM"); assert.equal(fb2.datePreference, "MD");
  fb2.recordDate("DM"); assert.equal(fb2.datePreference, "DM");
});
