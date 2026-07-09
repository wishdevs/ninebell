// pm2 로 Next.js 2 프로세스(클러스터). 둘이 3000 포트를 공유(pm2 cluster 소켓 공유).
module.exports = {
  apps: [
    {
      name: 'next',
      script: 'node_modules/next/dist/bin/next',
      args: 'start -p 3000',
      instances: 2,
      exec_mode: 'cluster',
      env: { NODE_ENV: 'production' },
    },
  ],
};
