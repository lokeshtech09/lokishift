import { APP_NAME, APP_NAME_PARTS } from '@/lib/brand';

/** Monogram: an Underground-grey "L" on silver with a red accent stroke. */
export function LogoMark({ className = 'h-9 w-9' }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="14" fill="#e8e9e6" />
      <path
        d="M22 14v30h20"
        fill="none"
        stroke="#585c55"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M36 14l8 8" stroke="#d23a43" strokeWidth="6" strokeLinecap="round" />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className="font-display text-xl font-extrabold tracking-tight text-brand-800">
        {APP_NAME_PARTS[0]}
        <span className="text-accent-500">{APP_NAME_PARTS[1]}</span>
      </span>
      <span className="sr-only">{APP_NAME}</span>
    </span>
  );
}
