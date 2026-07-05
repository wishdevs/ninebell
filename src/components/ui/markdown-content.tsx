import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * 채팅 메시지 공용 마크다운 렌더(GFM 표 지원). 어시스턴트 패널(MarkdownText)과
 * 라이브 실행 화면(LiveChatCard)이 동일한 토큰/스타일 규약을 쓰던 것을 하나로 합쳤다
 * — 표는 가로 스크롤·컴팩트, 코드/인용/제목/링크 스타일 포함.
 */
export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="flex flex-col gap-2 text-[length:var(--text-body-sm)] leading-relaxed [&_ol]:m-0 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:m-0 [&_ul]:m-0 [&_ul]:list-disc [&_ul]:pl-4">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="border-border my-1 overflow-x-auto rounded-[var(--radius-sm)] border">
              <table className="w-full border-collapse text-[11px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
          th: ({ children }) => (
            <th className="border-border/60 border-b px-2 py-1 text-left font-semibold whitespace-nowrap">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-border/40 border-t px-2 py-1 align-top whitespace-nowrap tabular-nums">
              {children}
            </td>
          ),
          h1: ({ children }) => (
            <h1 className="text-foreground mt-1 text-[13px] font-bold">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-foreground mt-1 text-[12.5px] font-bold">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-foreground mt-1 text-[12px] font-semibold">{children}</h3>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-accent/40 text-muted-foreground border-l-2 pl-2">
              {children}
            </blockquote>
          ),
          pre: ({ children }) => (
            <pre className="bg-background/60 border-border/60 my-1 overflow-x-auto rounded-[var(--radius-sm)] border p-2 font-mono text-[11px] leading-snug [&_code]:bg-transparent [&_code]:p-0">
              {children}
            </pre>
          ),
          strong: ({ children }) => (
            <strong className="text-foreground font-semibold">{children}</strong>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline underline-offset-2 hover:opacity-80"
            >
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="bg-background/60 rounded px-1 py-0.5 font-mono text-[11px]">
              {children}
            </code>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
