"use client";

interface ArcGaugeProps {
  value: number;
  max?: number;
  label: string;
  color: string;
  size?: number;
}

export function ArcGauge({ value, max = 10, label, color, size = 140 }: ArcGaugeProps) {
  const pct = Math.min(Math.max(value / max, 0), 1);

  // Arc goes from 210° to -30° (240° sweep, bottom-left to bottom-right)
  const START_ANGLE = 215;
  const SWEEP = 250;
  const R = size / 2 - 14;
  const cx = size / 2;
  const cy = size / 2;

  const toXY = (deg: number) => {
    const rad = ((deg - 90) * Math.PI) / 180;
    return { x: cx + R * Math.cos(rad), y: cy + R * Math.sin(rad) };
  };

  const endAngle = START_ANGLE + SWEEP * pct;

  const p1 = toXY(START_ANGLE);
  const p2 = toXY(START_ANGLE + SWEEP);
  const p3 = toXY(START_ANGLE);
  const p4 = toXY(endAngle);

  const largeArc = SWEEP > 180 ? 1 : 0;
  const fillLarge = SWEEP * pct > 180 ? 1 : 0;

  const trackPath = `M ${p1.x} ${p1.y} A ${R} ${R} 0 ${largeArc} 1 ${p2.x} ${p2.y}`;
  const fillPath  = pct > 0
    ? `M ${p3.x} ${p3.y} A ${R} ${R} 0 ${fillLarge} 1 ${p4.x} ${p4.y}`
    : "";

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Track */}
        <path d={trackPath} fill="none" stroke="#27272a" strokeWidth={10} strokeLinecap="round" />
        {/* Fill */}
        {fillPath && (
          <path d={fillPath} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round" />
        )}
        {/* Value */}
        <text x={cx} y={cy - 4} textAnchor="middle" fill="white"
          fontSize={size * 0.22} fontWeight="700" fontFamily="monospace">
          {value.toFixed(1)}
        </text>
        {/* Label */}
        <text x={cx} y={cy + size * 0.18} textAnchor="middle" fill="#71717a"
          fontSize={size * 0.1} fontFamily="system-ui">
          / {max}
        </text>
      </svg>
      <span className="text-xs font-semibold tracking-wide mt-1" style={{ color }}>
        {label}
      </span>
    </div>
  );
}
