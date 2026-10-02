interface BarrierGaugeProps {
  ticker: string;
  pctOfInitial: number | null;
  couponBarrierPct: number;
  downsideBarrierPct: number;
}

export default function BarrierGauge({
  ticker,
  pctOfInitial,
  couponBarrierPct,
  downsideBarrierPct,
}: BarrierGaugeProps) {
  if (pctOfInitial == null) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="text-gray-400 font-mono w-12">{ticker}</span>
        <span className="text-gray-500 italic">No data</span>
      </div>
    );
  }

  // Scale: 0% to 130% of initial price shown on the bar
  const scaleMin = 0;
  const scaleMax = 130;
  const clamp = (v: number) => Math.min(Math.max(v, scaleMin), scaleMax);
  const toPercent = (v: number) => ((clamp(v * 100) - scaleMin) / (scaleMax - scaleMin)) * 100;

  const currentPos = toPercent(pctOfInitial);
  const couponPos = toPercent(couponBarrierPct);
  const downsidePos = toPercent(downsideBarrierPct);

  const aboveCoupon = pctOfInitial >= couponBarrierPct;
  const aboveDownside = pctOfInitial >= downsideBarrierPct;

  let dotColor = 'bg-green-400';
  if (!aboveDownside) dotColor = 'bg-red-500';
  else if (!aboveCoupon) dotColor = 'bg-yellow-400';

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-gray-400 font-mono w-12 shrink-0">{ticker}</span>
      <div className="relative flex-1 h-3 bg-gray-700 rounded-full overflow-visible">
        {/* Downside barrier marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-red-500"
          style={{ left: `${downsidePos}%` }}
          title={`Downside barrier: ${(downsideBarrierPct * 100).toFixed(0)}%`}
        />
        {/* Coupon barrier marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-yellow-500"
          style={{ left: `${couponPos}%` }}
          title={`Coupon barrier: ${(couponBarrierPct * 100).toFixed(0)}%`}
        />
        {/* Current position dot */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full ${dotColor} ring-2 ring-gray-800`}
          style={{ left: `${currentPos}%`, transform: 'translate(-50%, -50%)' }}
          title={`Current: ${(pctOfInitial * 100).toFixed(1)}%`}
        />
      </div>
      <span className="text-gray-300 font-mono w-16 text-right shrink-0">
        {(pctOfInitial * 100).toFixed(1)}%
      </span>
    </div>
  );
}
