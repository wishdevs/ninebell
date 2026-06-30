'use client';

import { useState } from 'react';
import { RiAlertLine } from '@remixicon/react';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  message: React.ReactNode;
  /** Ask the user to type this string to enable the destructive action. */
  confirmWord?: string;
  /** Button label (default: "삭제"). */
  confirmLabel?: string;
  /** Variant controls confirm button color. */
  variant?: 'danger' | 'primary';
  onConfirm: () => void | Promise<void>;
}

export function ConfirmDialog({
  open,
  onClose,
  title,
  message,
  confirmWord,
  confirmLabel = '삭제',
  variant = 'danger',
  onConfirm,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requiresTyping = Boolean(confirmWord);
  const matches = !requiresTyping || typed.trim() === confirmWord;

  function reset() {
    setTyped('');
    setError(null);
  }

  function handleClose() {
    if (submitting) return;
    reset();
    onClose();
  }

  async function handleConfirm() {
    if (!matches) {
      setError(`확인을 위해 "${confirmWord}" 을(를) 정확히 입력해주세요.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm();
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '요청을 처리하지 못했습니다.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title={title} size="sm">
      <DialogBody>
        <div className="flex items-start gap-3">
          {variant === 'danger' ? (
            <span className="bg-danger/10 text-danger flex h-9 w-9 shrink-0 items-center justify-center rounded-full">
              <RiAlertLine size={18} />
            </span>
          ) : null}
          <div className="text-muted-foreground text-sm leading-relaxed">{message}</div>
        </div>

        {requiresTyping ? (
          <div className="grid gap-2">
            <Label htmlFor="confirm-word" className="text-xs">
              계속하려면 <span className="text-foreground font-mono">{confirmWord}</span> 을(를)
              입력하세요
            </Label>
            <Input
              id="confirm-word"
              type="text"
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={submitting}
              autoComplete="off"
            />
          </div>
        ) : null}

        {error ? (
          <p className="text-danger text-xs" role="alert">
            {error}
          </p>
        ) : null}
      </DialogBody>

      <footer className="border-border bg-muted/20 flex justify-end gap-2 border-t px-5 py-3">
        <Button type="button" variant="secondary" size="sm" onClick={handleClose}>
          취소
        </Button>
        <Button
          type="button"
          variant={variant}
          size="sm"
          onClick={handleConfirm}
          disabled={submitting || !matches}
        >
          {submitting ? '처리 중…' : confirmLabel}
        </Button>
      </footer>
    </Dialog>
  );
}
