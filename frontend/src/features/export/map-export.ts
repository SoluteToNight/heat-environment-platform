import type { EnvironmentView, PublicCheckIn, Scene, ViewItem } from '../../services/contracts';
import { effectiveTime, modeNames } from '../../services/format';

export async function composeMap(image: string, scene: Scene, view: EnvironmentView, item: ViewItem, title: string, demo: boolean, visibleLayers: string[], records: PublicCheckIn[]) {
  const bitmap = new Image(); bitmap.src = image;
  await bitmap.decode();
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1000, bitmap.width); canvas.height = Math.round(bitmap.height / bitmap.width * canvas.width) + 230;
  const context = canvas.getContext('2d'); if (!context) throw new Error('浏览器不支持地图导出');
  context.fillStyle = '#f7f8f4'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#263b36'; context.font = 'bold 26px "Microsoft YaHei", sans-serif'; context.fillText(`上海热环境探索 · ${scene.name}`, 32, 43);
  context.font = '15px "Microsoft YaHei", sans-serif'; context.fillText(`${title} · ${modeNames[view.mode]} · ${effectiveTime(item)}（上海时间）${demo ? ' · 合成演示' : ''}`, 32, 75);
  context.drawImage(bitmap, 0, 95, canvas.width, canvas.height - 230);
  const bottom = canvas.height - 113;
  const gradient = context.createLinearGradient(32, 0, 252, 0);
  item.legend.colors.forEach((color, index) => gradient.addColorStop(index / Math.max(1, item.legend.colors.length - 1), color));
  context.fillStyle = gradient; context.fillRect(32, bottom, 220, 12);
  context.fillStyle = '#263b36'; context.font = '13px "Microsoft YaHei", sans-serif'; context.fillText(`${item.legend.min}                 ${item.legend.max} ${item.unit}  ·  缺测不着色`, 32, bottom + 31);
  context.fillText(`视图 ${view.view_id} · ${item.freshness === 'stale' ? '数据已过期' : '固定版本'} · 公开体感 ${records.length} 条`, 290, bottom + 12);
  context.fillText(`可见图层：${visibleLayers.join('、')}。透视图无统一比例尺；方向以地图指北为准。`, 32, bottom + 57);
  context.fillText(scene.attribution.join(' / ').slice(0, 130), 32, bottom + 82);
  const url = canvas.toDataURL('image/png');
  if (url.length < 1000) throw new Error('地图导出为空，请重试。');
  return url;
}
export function downloadImage(url: string) {
  const link = document.createElement('a'); link.href = url; link.download = `上海热环境专题地图-${Date.now()}.png`; link.click();
}
