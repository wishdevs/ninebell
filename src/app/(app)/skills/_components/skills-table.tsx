'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import { fetchSkills, type SkillItem, type SkillLayer } from '@/lib/api/skills';

/** 계층 표시 라벨 + 톤 — 알 수 없는 값은 회색 원문 노출(카탈로그 진화 대비). */
const LAYER_META: Record<SkillLayer, { label: string; className: string }> = {
  omnisol: { label: '옴니솔', className: 'bg-info/10 text-info' },
  common: { label: '공통', className: 'bg-muted text-muted-foreground' },
  llm: { label: 'LLM', className: 'bg-accent/10 text-accent' },
};

function LayerBadge({ layer }: { layer: SkillItem['layer'] }) {
  const meta = LAYER_META[layer] ?? {
    label: layer,
    className: 'bg-muted text-muted-foreground',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}

/**
 * 스킬 카탈로그 표 — GET /skills 결과(카탈로그 순서 고정)를 그대로 표로 노출.
 * 사용 에이전트는 칩으로 렌더링하고 클릭 시 에이전트 상세로 이동한다.
 */
export function SkillsTable() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSkills()
      .then(setSkills)
      .catch((err) => toast.error(errorMessage(err, '스킬 카탈로그를 불러오지 못했습니다.')))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size={20} label="스킬 카탈로그 불러오는 중" />
      </div>
    );
  }

  if (skills.length === 0) {
    return (
      <EmptyState
        title="스킬 카탈로그가 비어 있습니다"
        description="백엔드 app/services/skills.py 에 스킬을 등록하면 여기 표시됩니다."
      />
    );
  }

  return (
    <SectionCard>
      <div className="overflow-x-auto">
        <table className="w-full text-[length:var(--text-body-sm)]">
          <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
            <tr>
              <Th>스킬</Th>
              <Th>설명</Th>
              <Th>계층</Th>
              <Th>사용 에이전트</Th>
            </tr>
          </thead>
          <tbody>
            {skills.map((skill) => (
              <tr key={skill.key} className="border-border/60 border-t">
                <Td>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-foreground font-medium">{skill.label}</span>
                    <span className="text-foreground-tertiary font-mono text-[11px]">
                      {skill.key}
                    </span>
                  </div>
                </Td>
                <Td className="text-foreground-secondary">{skill.description}</Td>
                <Td>
                  <LayerBadge layer={skill.layer} />
                </Td>
                <Td>
                  {skill.agents.length === 0 ? (
                    <span className="text-foreground-tertiary">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {skill.agents.map((agent) => (
                        <Link
                          key={agent.id}
                          href={`/agents/${agent.id}`}
                          className="border-border text-foreground-secondary hover:bg-muted/60 hover:text-foreground inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors"
                        >
                          {agent.name}
                        </Link>
                      ))}
                    </div>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
