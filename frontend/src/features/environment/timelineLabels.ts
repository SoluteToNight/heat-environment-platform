// 时间轴刻度选取：跨天范围以上海时间（UTC+8，无夏令时）00:00 的天界为锚点，
// 让每个刻度同时承担“日期分隔 + 时刻”两个信息；半天以内的短范围退回等分四档。
const DAY_MS = 86_400_000;
const SHANGHAI_UTC_OFFSET_HOURS = 8;

export function pickTimelineLabels(times: string[]): number[] {
  if (times.length <= 4) return times.map((_, index) => index);
  const first = Date.parse(times[0]!);
  const last = Date.parse(times.at(-1)!);
  if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return [0, times.length - 1];
  if (last - first <= (18 / 24) * DAY_MS) {
    const lastIndex = times.length - 1;
    return [...new Set([0, Math.round(lastIndex / 3), Math.round((lastIndex * 2) / 3), lastIndex])].sort((a, b) => a - b);
  }
  const indices = new Set<number>([0, times.length - 1]);
  times.forEach((time, index) => {
    const moment = new Date(time);
    if ((moment.getUTCHours() + SHANGHAI_UTC_OFFSET_HOURS) % 24 === 0 && moment.getUTCMinutes() === 0) indices.add(index);
  });
  return [...indices].sort((a, b) => a - b);
}
