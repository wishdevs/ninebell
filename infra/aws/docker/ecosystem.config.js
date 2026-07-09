// pm2 로 Next.js 2 프로세스(클러스터). 커스텀 server.js 를 fork(포트 3000 공유).
// next CLI 를 cluster 로 돌리면 프로젝트 디렉토리 오인식 → server.js 사용.
module.exports = {
  apps: [
    {
      name: 'next',
      script: 'server.js',
      instances: 2,
      exec_mode: 'cluster',
      env: { NODE_ENV: 'production' },
    },
  ],
};
