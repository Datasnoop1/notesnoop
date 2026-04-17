/**
 * PrintLogo — despite the name, now renders a plain-text "Generated on
 * www.datasnoop.be" attribution that appears only in the printed PDF.
 * Kept as a component so the two callers (company page header + demo
 * page header) share the exact same markup/styling. Hidden on screen
 * via Tailwind `hidden print:block`.
 */

interface PrintLogoProps {
  /** Ignored — kept in the signature so existing callers don't need to change. */
  heightPx?: number;
  className?: string;
}

export default function PrintLogo({ className = "" }: PrintLogoProps) {
  return (
    <div className={`hidden print:block shrink-0 text-[9pt] text-slate-500 ${className}`}>
      Generated on{" "}
      <span className="font-semibold text-slate-700">www.datasnoop.be</span>
    </div>
  );
}
