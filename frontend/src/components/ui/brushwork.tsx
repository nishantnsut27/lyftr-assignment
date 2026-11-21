import { useMotionPreferences } from './use-motion-preferences';

export function Brushwork() {
  const { hidden, reducedMotion } = useMotionPreferences();
  return (
    <div
      className="brushwork"
      aria-hidden="true"
      data-paused={hidden || reducedMotion}
    >
      <svg
        viewBox="0 0 1440 1000"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <g className="brush-drift">
          <path
            d="M-130 1010C-20 720 160 890 240 580S100 170-140 130"
            stroke="#D90000"
            strokeWidth="24"
          />
          <path
            d="M-100 1000C0 760 150 870 220 560"
            stroke="#FFEA93"
            strokeWidth="2"
          />
          <path
            d="M1570-80C1230 100 1490 350 1310 550S1420 910 1590 910"
            stroke="#8DB355"
            strokeWidth="18"
          />
          <path
            d="M1580-65C1270 110 1510 360 1340 570"
            stroke="#FFEA93"
            strokeWidth="2"
          />
        </g>
      </svg>
    </div>
  );
}
