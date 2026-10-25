// Inline stroke icons (no emoji, no icon font): persona portraits, locks, and the Nexus mark.
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export function PersonaIcon({ icon }: { icon: string }) {
  return (
    <svg viewBox="0 0 24 24" width="55%" height="55%" aria-hidden="true" {...stroke}>
      {icon === "search" && (<><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5M8.5 11h5" /></>)}
      {icon === "dial" && (<><path d="M4 16a8 8 0 1 1 16 0" /><path d="M12 16l4-6" /><circle cx="12" cy="16" r="1.4" /></>)}
      {icon === "lock" && (<><rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5M12 14.5v2.5" /></>)}
      {icon === "bolt" && <path d="M13 3L5 13.5h6L10 21l8-10.5h-6L13 3z" />}
      {icon === "book" && (<><path d="M5 4.5h11a3 3 0 0 1 3 3v12H8a3 3 0 0 1-3-3v-12z" /><path d="M9 9h6M9 12.5h6M9 16h4" /></>)}
    </svg>
  );
}

export function LockIcon({ state }: { state: "pending" | "run" | "open" | "fail" }) {
  return (
    <svg viewBox="0 0 24 24" className="ic" aria-hidden="true" {...stroke}>
      {state === "fail" ? (
        <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4.5M12 17.5v.5" /></>
      ) : state === "open" ? (
        <><rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8 10.5V7a4 4 0 0 1 7.6-1.7" /></>
      ) : (
        <><rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></>
      )}
    </svg>
  );
}

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect x="1" y="1" width="26" height="26" rx="7" fill="none" stroke="#22D3EE" strokeWidth="1.5" />
      <path d="M8 19V9l12 10V9" fill="none" stroke="#22D3EE" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
