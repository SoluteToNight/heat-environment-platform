import { describe, expect, it } from 'vitest';
import { pickTimelineLabels } from '../features/environment/timelineLabels';

const hourly = (startIso: string, count: number) => Array.from({ length: count }, (_, index) => new Date(Date.parse(startIso) + index * 3600_000).toISOString());

describe('timeline label picking', () => {
  it('labels every frame when the series is short', () => {
    expect(pickTimelineLabels(['2026-09-19T04:00:00Z', '2026-09-19T05:00:00Z', '2026-09-19T06:00:00Z'])).toEqual([0, 1, 2]);
  });

  it('splits a sub-day range into four even ticks', () => {
    expect(pickTimelineLabels(hourly('2026-09-19T04:00:00Z', 13))).toEqual([0, 4, 8, 12]);
  });

  it('anchors multi-day ranges to Shanghai midnight boundaries plus endpoints', () => {
    const times = hourly('2026-09-19T04:00:00Z', 48); // 上海 09-19 12:00 → 09-21 11:00
    expect(pickTimelineLabels(times)).toEqual([0, 12, 36, 47]);
    expect(pickTimelineLabels(times).map(index => times[index])).toEqual([
      '2026-09-19T04:00:00.000Z',
      '2026-09-19T16:00:00.000Z',
      '2026-09-20T16:00:00.000Z',
      '2026-09-21T03:00:00.000Z',
    ]);
  });

  it('keeps exact midnight frames of a 15-minute dilated three-day window', () => {
    const hours = hourly('2026-09-18T16:00:00Z', 72); // 上海昨日 00:00 → 明日 23:00
    const times = hours.flatMap(hour => [0, 15, 30, 45].map(minutes => new Date(Date.parse(hour) + minutes * 60_000).toISOString())).slice(0, -3);
    expect(pickTimelineLabels(times)).toEqual([0, 96, 192, 284]);
  });
});
