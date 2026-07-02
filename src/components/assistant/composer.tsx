'use client';

import { useState } from 'react';
import { RiLoader4Line, RiSendPlaneLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';

interface ComposerProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState('');

  const submit = () => {
    if (!text.trim() || disabled) return;
    onSend(text);
    setText('');
  };

  return (
    <div className="border-border bg-surface-raised flex items-end gap-2 rounded-[var(--radius-md)] border p-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            // 한글/일본어 등 IME 조합 중 Enter 는 '조합 확정'용이다. 이때 전송·클리어하면
            // 마지막 글자가 compositionend 로 입력창에 다시 남는다(가나다 → '다' 잔류). 조합 중엔 무시.
            if (e.nativeEvent.isComposing || e.keyCode === 229) return;
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        aria-label="AI 어시스턴트에게 보낼 메시지"
        placeholder="AI 어시스턴트에게 질문하거나 실행을 요청하세요…"
        className="text-foreground placeholder:text-muted-foreground max-h-32 min-h-9 flex-1 resize-none bg-transparent text-[length:var(--text-body-sm)] outline-none disabled:opacity-50"
      />
      <Button size="icon" onClick={submit} disabled={disabled || !text.trim()} aria-label="전송">
        {disabled ? (
          <RiLoader4Line size={15} aria-hidden className="animate-spin" />
        ) : (
          <RiSendPlaneLine size={15} aria-hidden />
        )}
      </Button>
    </div>
  );
}
