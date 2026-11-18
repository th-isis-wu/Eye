/* Tesseract.js 워커 감싸기: 언어 데이터 주소를 배포 가능한 확장자(.wasm)로 바꿔 불러온다. */
const nativeFetch = self.fetch.bind(self);
self.fetch = (url, opts) => nativeFetch(String(url).replace(/\.traineddata(\.gz)?$/, ".traineddata$1.wasm"), opts);
importScripts("vendor/worker.min.js");
