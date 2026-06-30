/**
 * Avatar display with graceful fallback to initials.
 *
 * When ``hasAvatar`` is true the image is loaded through the BFF proxy at
 * /api/users/{userId}/avatar, which keeps the MinIO bucket private. When
 * absent, we render a coloured circle with up to two initials derived from
 * the user's full name or email.
 */

interface AvatarProps {
  userId: string;
  hasAvatar: boolean;
  label: string;
  size?: number;
  className?: string;
  /**
   * A cache-buster suffix ?v=<n> that you can bump to force a reload after
   * an upload (browsers aggressively cache image responses even when
   * cache-control is no-store on the HTML doc).
   */
  cacheKey?: string | number;
}

function initialsFrom(label: string): string {
  const cleaned = label.trim();
  if (!cleaned) return '?';
  const parts = cleaned.split(/\s+/);
  if (parts.length === 1) {
    return cleaned.slice(0, 2).toUpperCase();
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Avatar({
  userId,
  hasAvatar,
  label,
  size = 64,
  className = '',
  cacheKey,
}: AvatarProps) {
  const dimension = { width: size, height: size } as const;

  if (hasAvatar) {
    const src = `/api/users/${userId}/avatar${cacheKey != null ? `?v=${cacheKey}` : ''}`;
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={`${label} 아바타`}
        width={size}
        height={size}
        className={`border-border rounded-full border object-cover ${className}`}
        style={dimension}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`border-border bg-surface text-muted-foreground inline-flex items-center justify-center rounded-full border font-mono text-sm font-semibold uppercase ${className}`}
      style={dimension}
    >
      {initialsFrom(label)}
    </span>
  );
}
