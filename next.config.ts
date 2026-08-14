import type { NextConfig } from 'next';

// Next 16은 `next build` 시 ESLint를 실행하지 않으므로 별도 설정이 필요 없다.
const nextConfig: NextConfig = {
  // Docker 프로덕션 이미지용 — .next/standalone(최소 server.js) 산출.
  output: 'standalone',
};

export default nextConfig;
