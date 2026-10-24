import React, { useState, useMemo } from "react";
import { Activity, Info, Filter } from "lucide-react";

export function VitalsChart({ chartSeries, onSelectEvent, selectedEventId }) {
  const [activeFilter, setActiveFilter] = useState("all"); // "all" | "bp" | "hr" | "spo2" | "rr" | "temp"
  const [hoveredPoint, setHoveredPoint] = useState(null);

  // Collect all unique chronological timestamps across all series
  const allPoints = useMemo(() => {
    if (!chartSeries) return [];
    const list = [];
    Object.entries(chartSeries).forEach(([seriesKey, points]) => {
      (points || []).forEach((pt) => {
        list.push({ ...pt, seriesKey });
      });
    });
    list.sort((a, b) => a.sort_key - b.sort_key);
    return list;
  }, [chartSeries]);

  const uniqueTimes = useMemo(() => {
    const set = new Set();
    const sorted = [];
    allPoints.forEach((p) => {
      if (!set.has(p.time)) {
        set.add(p.time);
        sorted.push({ time: p.time, sort_key: p.sort_key });
      }
    });
    sorted.sort((a, b) => a.sort_key - b.sort_key);
    return sorted;
  }, [allPoints]);

  const hasData = allPoints.length > 0;

  // Chart Dimensions & Layout
  const svgWidth = 800;
  const svgHeight = 280;
  const paddingLeft = 55;
  const paddingRight = 40;
  const paddingTop = 25;
  const paddingBottom = 45;

  const chartWidth = svgWidth - paddingLeft - paddingRight;
  const chartHeight = svgHeight - paddingTop - paddingBottom;

  // Calculate X position by chronological time index
  const timeToX = useMemo(() => {
    const map = new Map();
    if (uniqueTimes.length === 0) return map;
    if (uniqueTimes.length === 1) {
      map.set(uniqueTimes[0].time, paddingLeft + chartWidth / 2);
      return map;
    }
    const step = chartWidth / (uniqueTimes.length - 1);
    uniqueTimes.forEach((ut, idx) => {
      map.set(ut.time, paddingLeft + idx * step);
    });
    return map;
  }, [uniqueTimes, chartWidth, paddingLeft]);

  // Determine Y-scale based on active filter
  const yDomain = useMemo(() => {
    if (activeFilter === "bp") return { min: 40, max: 200, unit: "mmHg", label: "Blood Pressure (mmHg)" };
    if (activeFilter === "hr") return { min: 40, max: 180, unit: "bpm", label: "Heart Rate (bpm)" };
    if (activeFilter === "spo2") return { min: 80, max: 100, unit: "%", label: "Oxygen Saturation (%)" };
    if (activeFilter === "rr") return { min: 8, max: 40, unit: "breaths/min", label: "Resp Rate (bpm)" };
    if (activeFilter === "temp") return { min: 35, max: 41, unit: "°C", label: "Temperature (°C)" };
    // Default multi-vital scale (0 to 200)
    return { min: 0, max: 200, unit: "Value", label: "Clinical Value" };
  }, [activeFilter]);

  const valueToY = (val, min = yDomain.min, max = yDomain.max) => {
    const clamped = Math.max(min, Math.min(max, val));
    const ratio = (clamped - min) / (max - min);
    return paddingTop + chartHeight - ratio * chartHeight;
  };

  // Series Configuration
  const seriesConfig = {
    systolic: {
      label: "Systolic BP",
      color: "#dc2626", // Red-600
      dash: "none",
      filterGroup: "bp",
      min: 40, max: 200
    },
    diastolic: {
      label: "Diastolic BP",
      color: "#ea580c", // Orange-600
      dash: "4,3",
      filterGroup: "bp",
      min: 40, max: 200
    },
    heart_rate: {
      label: "Heart Rate",
      color: "#0d9488", // Teal-600
      dash: "none",
      filterGroup: "hr",
      min: 40, max: 180
    },
    oxygen_saturation: {
      label: "SpO2 (%)",
      color: "#2563eb", // Blue-600
      dash: "none",
      filterGroup: "spo2",
      min: 80, max: 100
    },
    respiratory_rate: {
      label: "Resp Rate",
      color: "#7c3aed", // Purple-600
      dash: "2,2",
      filterGroup: "rr",
      min: 8, max: 40
    },
    temperature: {
      label: "Temperature",
      color: "#d97706", // Amber-600
      dash: "none",
      filterGroup: "temp",
      min: 35, max: 41
    }
  };

  // Build SVG Path for a series
  const buildPath = (pts, sKey) => {
    if (!pts || pts.length === 0) return null;
    const sorted = [...pts].sort((a, b) => a.sort_key - b.sort_key);
    const cfg = seriesConfig[sKey];

    const min = activeFilter === "all" ? (cfg.min || yDomain.min) : yDomain.min;
    const max = activeFilter === "all" ? (cfg.max || yDomain.max) : yDomain.max;

    const coords = sorted
      .map((p) => {
        const x = timeToX.get(p.time);
        const y = valueToY(p.value, min, max);
        return x !== undefined ? `${x},${y}` : null;
      })
      .filter(Boolean);

    if (coords.length === 0) return null;
    if (coords.length === 1) return null; // Single points rendered as circles
    return `M ${coords.join(" L ")}`;
  };

  // Y-axis grid tick marks (5 ticks)
  const yTicks = useMemo(() => {
    const ticks = [];
    const count = 5;
    for (let i = 0; i <= count; i++) {
      const val = yDomain.min + (i * (yDomain.max - yDomain.min)) / count;
      const y = paddingTop + chartHeight - (i * chartHeight) / count;
      ticks.push({ val: Math.round(val * 10) / 10, y });
    }
    return ticks;
  }, [yDomain, chartHeight, paddingTop]);

  if (!hasData) {
    return (
      <div className="bg-white p-8 rounded-xl border border-slate-200 text-center space-y-2">
        <Activity className="w-8 h-8 text-slate-300 mx-auto" />
        <h3 className="text-sm font-bold text-slate-700">No Plottable Vital Sign Measurements</h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          No timestamped physiological observations were detected for this encounter. Chronological values will appear automatically as vital signs with event times are recorded.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
      {/* Header and Filter Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-clinical-teal-600 shrink-0" />
          <div>
            <h3 className="text-sm font-bold text-slate-900">Vital-Signs Progression Chart</h3>
            <p className="text-xs text-slate-500">
              Interactive timeline of physiological observations. Click any data point to inspect verbatim evidence.
            </p>
          </div>
        </div>

        {/* Filter Buttons */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-[11px] font-semibold text-slate-400 mr-1 flex items-center gap-1">
            <Filter className="w-3 h-3" /> Filter:
          </span>
          {[
            { id: "all", label: "All Series" },
            { id: "bp", label: "Blood Pressure" },
            { id: "hr", label: "Heart Rate" },
            { id: "spo2", label: "SpO2" },
            { id: "rr", label: "Resp Rate" },
            { id: "temp", label: "Temp" }
          ].map((btn) => (
            <button
              key={btn.id}
              onClick={() => setActiveFilter(btn.id)}
              className={`px-2.5 py-1 rounded-md font-semibold text-xs transition-colors ${
                activeFilter === btn.id
                  ? "bg-slate-900 text-white shadow-sm"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-700"
              }`}
            >
              {btn.label}
            </button>
          ))}
        </div>
      </div>

      {/* SVG Chart Container */}
      <div className="relative w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="w-full h-auto min-w-[500px] select-none"
        >
          {/* Y-axis Grid Lines */}
          {yTicks.map((tick, i) => (
            <g key={i}>
              <line
                x1={paddingLeft}
                y1={tick.y}
                x2={paddingLeft + chartWidth}
                y2={tick.y}
                stroke="#e2e8f0"
                strokeWidth="1"
                strokeDasharray="2,2"
              />
              <text
                x={paddingLeft - 8}
                y={tick.y + 3.5}
                textAnchor="end"
                fontSize="10"
                fill="#64748b"
                fontFamily="sans-serif"
              >
                {tick.val}
              </text>
            </g>
          ))}

          {/* X-axis Ticks & Labels */}
          {uniqueTimes.map((ut, i) => {
            const x = timeToX.get(ut.time);
            return (
              <g key={i}>
                <line
                  x1={x}
                  y1={paddingTop + chartHeight}
                  x2={x}
                  y2={paddingTop + chartHeight + 5}
                  stroke="#94a3b8"
                  strokeWidth="1"
                />
                <text
                  x={x}
                  y={paddingTop + chartHeight + 18}
                  textAnchor="middle"
                  fontSize="10"
                  fontWeight="600"
                  fill="#475569"
                  fontFamily="sans-serif"
                >
                  {ut.time}
                </text>
              </g>
            );
          })}

          {/* X & Y Baseline Rules */}
          <line
            x1={paddingLeft}
            y1={paddingTop + chartHeight}
            x2={paddingLeft + chartWidth}
            y2={paddingTop + chartHeight}
            stroke="#475569"
            strokeWidth="1.5"
          />
          <line
            x1={paddingLeft}
            y1={paddingTop}
            x2={paddingLeft}
            y2={paddingTop + chartHeight}
            stroke="#475569"
            strokeWidth="1.5"
          />

          {/* Render Paths & Points for active series */}
          {Object.entries(chartSeries || {}).map(([sKey, pts]) => {
            const cfg = seriesConfig[sKey];
            if (!cfg) return null;
            if (activeFilter !== "all" && cfg.filterGroup !== activeFilter) return null;

            const pathD = buildPath(pts, sKey);
            const min = activeFilter === "all" ? (cfg.min || yDomain.min) : yDomain.min;
            const max = activeFilter === "all" ? (cfg.max || yDomain.max) : yDomain.max;

            return (
              <g key={sKey}>
                {pathD && (
                  <path
                    d={pathD}
                    fill="none"
                    stroke={cfg.color}
                    strokeWidth="2.5"
                    strokeDasharray={cfg.dash}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                )}

                {/* Data Points */}
                {(pts || []).map((p, idx) => {
                  const cx = timeToX.get(p.time);
                  const cy = valueToY(p.value, min, max);
                  if (cx === undefined) return null;
                  const isSelected = selectedEventId === p.event_id;

                  return (
                    <g
                      key={idx}
                      className="cursor-pointer transition-transform"
                      onClick={() => onSelectEvent && onSelectEvent(p.event_id)}
                      onMouseEnter={() => setHoveredPoint({ ...p, sKey, cfg, cx, cy })}
                      onMouseLeave={() => setHoveredPoint(null)}
                    >
                      {/* Interactive Touch/Click Halo */}
                      <circle cx={cx} cy={cy} r="14" fill="transparent" />

                      {/* Visible Point */}
                      <circle
                        cx={cx}
                        cy={cy}
                        r={isSelected ? "6" : "4.5"}
                        fill={cfg.color}
                        stroke="#ffffff"
                        strokeWidth={isSelected ? "2.5" : "1.5"}
                        className="hover:scale-125 transition-transform"
                      />
                    </g>
                  );
                })}
              </g>
            );
          })}

          {/* Interactive Tooltip Overlay */}
          {hoveredPoint && (
            <g
              transform={`translate(${
                hoveredPoint.cx > svgWidth - 140 ? hoveredPoint.cx - 130 : hoveredPoint.cx + 10
              }, ${
                hoveredPoint.cy > 70 ? hoveredPoint.cy - 50 : hoveredPoint.cy + 10
              })`}
              pointerEvents="none"
            >
              <rect
                width="120"
                height="44"
                rx="6"
                fill="#0f172a"
                opacity="0.92"
                stroke="#334155"
                strokeWidth="0.5"
              />
              <text x="8" y="15" fill="#f8fafc" fontSize="9" fontWeight="bold">
                {hoveredPoint.cfg.label}: {hoveredPoint.value} {hoveredPoint.unit}
              </text>
              <text x="8" y="27" fill="#cbd5e1" fontSize="8">
                Time: {hoveredPoint.time.includes("IST") ? hoveredPoint.time : `${hoveredPoint.time} IST`}
              </text>
              <text x="8" y="38" fill="#94a3b8" fontSize="7.5" fontStyle="italic">
                Click to inspect evidence
              </text>
            </g>
          )}
        </svg>
      </div>

      {/* Series Legend */}
      <div className="flex flex-wrap items-center justify-center gap-4 text-xs font-semibold text-slate-700 pt-1">
        {Object.entries(seriesConfig).map(([k, cfg]) => {
          if (activeFilter !== "all" && cfg.filterGroup !== activeFilter) return null;
          return (
            <div key={k} className="flex items-center gap-1.5">
              <span
                className="w-3.5 h-1.5 rounded-full inline-block"
                style={{ backgroundColor: cfg.color }}
              />
              <span>{cfg.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

