import { FileText } from 'lucide-react';
import { SectionCard } from '@/components/ui/section-card';
import { PROJECT_FILES } from '@/lib/data/projects';
import { formatRelativeKorean } from '@/lib/data/format';

/**
 * 파일 탭 — 프로젝트에 첨부된 파일 테이블(이름·종류·크기·올린 사람·수정 시각).
 */
export function FilesTab() {
  return (
    <SectionCard caption="자료" title={`파일 ${PROJECT_FILES.length}건`} density="comfortable">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] border-collapse text-left">
          <thead>
            <tr className="text-foreground-tertiary text-[length:var(--text-caption)] tracking-[0.06em] uppercase">
              <th className="pb-2 font-medium">이름</th>
              <th className="pb-2 font-medium">종류</th>
              <th className="pb-2 text-right font-medium">크기</th>
              <th className="pb-2 font-medium">올린 사람</th>
              <th className="pb-2 text-right font-medium">수정</th>
            </tr>
          </thead>
          <tbody>
            {PROJECT_FILES.map((file) => (
              <tr key={file.id} className="border-border-subtle row-hover border-t">
                <td className="py-2.5">
                  <span className="flex items-center gap-2">
                    <FileText size={15} className="text-foreground-tertiary shrink-0" aria-hidden />
                    <span className="text-foreground text-sm font-medium">{file.name}</span>
                  </span>
                </td>
                <td className="text-muted-foreground py-2.5 text-sm">{file.kind}</td>
                <td className="text-foreground-secondary py-2.5 text-right text-sm tabular-nums">
                  {file.size}
                </td>
                <td className="text-muted-foreground py-2.5 text-sm">{file.uploadedBy}</td>
                <td className="text-muted-foreground py-2.5 text-right text-sm tabular-nums">
                  {formatRelativeKorean(file.at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
