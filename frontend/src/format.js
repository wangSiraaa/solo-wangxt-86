export function fmtMoney(v) {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtPct(ratio) {
  if (ratio === null || ratio === undefined) return "—";
  return `${(Number(ratio) * 100).toFixed(4)}%`;
}

export const STATUS_CLASS = {
  RECOGNIZED: "badge green",
  PLANNED: "badge blue",
  PENDING: "badge amber",
};
