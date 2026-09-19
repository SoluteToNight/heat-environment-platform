<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AppIcon from '../../components/AppIcon.vue';
import { useWorkspace } from '../../stores/workspace';
import { localTime } from '../../services/format';
import { pickTimelineLabels } from './timelineLabels';

const store = useWorkspace();
const dragging = ref(false);
const preview = ref(0);

const committedIndex = computed(() => {
  const target = Date.parse(store.activeItem?.resolved_time || store.view?.requested_time || '');
  if (!Number.isFinite(target) || !store.times.length) return 0;
  return store.times.reduce((best, time, index) => Math.abs(Date.parse(time) - target) < Math.abs(Date.parse(store.times[best]!) - target) ? index : best, 0);
});
watch(committedIndex, value => { if (!dragging.value) preview.value = value; }, { immediate: true });

const labels = computed(() => pickTimelineLabels(store.times));

function labelStyle(index: number): Record<string, string> {
  if (index <= 0) return { left: '0%' };
  if (index >= store.times.length - 1) return { left: '100%', transform: 'translateX(-100%)' };
  return { left: `${((index / Math.max(1, store.times.length - 1)) * 100).toFixed(3)}%`, transform: 'translateX(-50%)' };
}

let dragTimer: ReturnType<typeof setTimeout> | undefined;
function onInput() {
  dragging.value = true;
  store.stop();
  clearTimeout(dragTimer);
  const targetTime = store.times[preview.value];
  if (!targetTime) return;

  if (store.isTimeCached(targetTime)) {
    void store.switchView({ kind: 'at', time: targetTime });
    return;
  }

  dragTimer = setTimeout(() => {
    if (dragging.value && store.times[preview.value]) {
      void store.switchView({ kind: 'at', time: store.times[preview.value]! });
    }
  }, 80);
}

function commit() {
  clearTimeout(dragTimer);
  dragging.value = false;
  store.stop();
  if (store.times[preview.value]) void store.switchView({ kind: 'at', time: store.times[preview.value]! });
}
</script>

<template>
  <div class="timeline-panel flex flex-col justify-between">
    <!-- Spatio-temporal Timeline Player -->
    <div class="flex-1 min-w-0 flex flex-col justify-between">
      <div class="flex items-center gap-3">
        <button
          class="button h-8 min-h-8 px-2.5 text-xs shrink-0"
          :class="store.timeSelection.kind === 'now' ? 'bg-green-soft text-accent font-semibold' : ''"
          :disabled="!store.scene"
          @click="store.stop(); store.switchView({ kind: 'now' })"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-accent" />现在
        </button>
        <div class="min-w-0">
          <p class="text-[11px] font-medium leading-none text-ink">{{ dragging ? '预览时刻' : '场景时刻' }}</p>
          <p class="mt-0.5 truncate text-[11px] text-muted">{{ localTime(dragging ? store.times[preview] : store.view?.requested_time, true) }}</p>
        </div>
        <span class="ml-auto hidden text-[11px] text-muted sm:inline">上海时间</span>
        <span v-if="store.busy" class="loader size-3.5" aria-label="正在加载时刻" />
      </div>

      <div class="mt-2 flex items-center gap-3">
        <button
          class="icon-button shrink-0 size-8 rounded-full bg-accent! text-white!"
          :disabled="!store.view"
          :aria-label="store.playing ? '暂停播放' : '逐时演变播放'"
          @click="store.play"
        >
          <AppIcon :name="store.playing ? 'pause' : 'play'" :size="14" />
        </button>
        <div class="min-w-0 flex-1">
          <input
            v-model.number="preview"
            class="w-full h-1.5 accent-accent"
            type="range"
            min="0"
            :max="Math.max(0, store.times.length - 1)"
            step="1"
            :disabled="!store.times.length"
            aria-label="选择场景时刻"
            :aria-valuetext="localTime(store.times[preview], true)"
            @input="onInput"
            @change="commit"
          />
          <div class="relative mt-1 h-4 text-[10px] leading-4 text-muted tabular-nums">
            <span v-for="index in labels" :key="index" class="absolute whitespace-nowrap" :style="labelStyle(index)">{{ localTime(store.times[index], true) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
