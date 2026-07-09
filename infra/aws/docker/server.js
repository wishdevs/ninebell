// Next.js 커스텀 서버 — pm2 cluster 모드(2 인스턴스)로 포트 공유하려면 next CLI 가 아니라
// 이런 Node 엔트리가 필요하다(CLI 는 cluster fork 시 프로젝트 디렉토리를 오인식). cwd=/app 기준.
const { createServer } = require('http');
const next = require('next');

const port = parseInt(process.env.PORT || '3000', 10);
const app = next({ dev: false });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  createServer((req, res) => handle(req, res)).listen(port, () => {
    // eslint-disable-next-line no-console
    console.log(`next ready on :${port} (pid ${process.pid})`);
  });
});
