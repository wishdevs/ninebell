import { Label } from './label';

interface FormFieldProps {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}

export function FormField({ id, label, error, hint, required, children }: FormFieldProps) {
  return (
    // content-start: 2열 그리드에서 셀이 행 높이에 맞춰 늘어날 때(align-items 기본 stretch)
    // 내부 행(레이블·입력·힌트)까지 같이 늘어나 입력칸이 아래로 밀리는 것을 막는다.
    // hint 가 한쪽에만 있으면 같은 행의 좌/우 입력이 12px 어긋났다(2026-08-25 실측).
    <div className="grid content-start gap-2">
      <Label htmlFor={id}>
        {label}
        {required ? <span className="text-danger ml-1">*</span> : null}
      </Label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-danger text-xs leading-relaxed">
          {error}
        </p>
      ) : hint ? (
        <p className="text-muted-foreground text-xs">{hint}</p>
      ) : null}
    </div>
  );
}
