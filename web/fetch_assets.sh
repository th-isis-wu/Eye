#!/usr/bin/env bash
# 웹 앱이 쓰는 OCR 엔진·PDF 리더·한국어 데이터를 web/ 아래에 내려받는다 (npm 필요).
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && for p in tesseract.js@5.1.1 tesseract.js-core@5.1.1 pdfjs-dist@3.11.174 \
   ; do
  name=$(npm pack -q "$p" | tail -1); mkdir -p "x/$p"; tar xzf "$name" -C "x/$p"; done)
x="$tmp/x"
mkdir -p vendor/core tessdata cmaps
cp "$x/tesseract.js@5.1.1/package/dist/tesseract.min.js" "$x/tesseract.js@5.1.1/package/dist/worker.min.js" vendor/
cp "$x/tesseract.js-core@5.1.1/package/tesseract-core-simd-lstm.wasm.js" \
   "$x/tesseract.js-core@5.1.1/package/tesseract-core-lstm.wasm.js" vendor/core/
cp "$x/pdfjs-dist@3.11.174/package/legacy/build/pdf.min.js" "$x/pdfjs-dist@3.11.174/package/legacy/build/pdf.worker.min.js" vendor/
# 정확도가 더 좋은 tessdata_fast 모델 (tesseract-ocr-kor 패키지와 같은 파일)
curl -sSL https://github.com/tesseract-ocr/tessdata_fast/raw/main/kor.traineddata | gzip -9 > tessdata/kor.traineddata.gz.wasm
curl -sSL https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata | gzip -9 > tessdata/eng.traineddata.gz.wasm
for f in "$x/pdfjs-dist@3.11.174/package/cmaps/"{Adobe-Korea1-*,UniKS-*,KSC*}.bcmap; do cp "$f" "cmaps/$(basename "$f").wasm"; done
echo "완료: vendor/ tessdata/ cmaps/"
