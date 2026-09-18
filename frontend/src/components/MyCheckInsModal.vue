<script setup lang="ts">
import { ref, watch } from 'vue';
import AppDialog from './AppDialog.vue';
import AppIcon from './AppIcon.vue';
import { api, errorMessage } from '../services/api';
import type { CheckIn } from '../services/contracts';
import { localTime, matchNames, sensationNames } from '../services/format';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; edit: [record: CheckIn]; deleted: [] }>();

const records = ref<CheckIn[]>([]);
const loading = ref(false);
const error = ref('');
const deletingId = ref<string | null>(null);

async function loadRecords() {
  loading.value = true;
  error.value = '';
  try {
    const res = await api.myRecords();
    records.value = res.items;
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    loadRecords();
  }
});

async function handleDelete(record: CheckIn) {
  if (!confirm(`确定要删除此条体感记录吗？（ID: ${record.check_in_id}）`)) return;
  deletingId.value = record.check_in_id;
  try {
    await api.remove(record.check_in_id, record.revision);
    records.value = records.value.filter(r => r.check_in_id !== record.check_in_id);
    emit('deleted');
  } catch (err) {
    alert(errorMessage(err));
  } finally {
    deletingId.value = null;
  }
}
</script>

<template>
  <AppDialog :open="open" title="我的体感打卡记录" wide @close="emit('close')">
    <div class="space-y-4">
      <div class="flex items-center justify-between text-xs text-muted">
        <span>共 {{ records.length }} 条个人打卡记录</span>
        <button class="text-button" :disabled="loading" @click="loadRecords">
          <AppIcon name="clock" :size="14" />
          刷新列表
        </button>
      </div>

      <div v-if="loading" class="py-12 text-center">
        <span class="loader mx-auto" />
        <p class="mt-3 text-xs text-muted">正在加载个人记录...</p>
      </div>

      <div v-else-if="error" class="status-warning" role="alert">
        {{ error }}
      </div>

      <div v-else-if="records.length === 0" class="py-12 text-center text-muted">
        <AppIcon name="pin" :size="32" class="mx-auto text-line mb-3" />
        <p class="text-sm font-medium">暂无打卡记录</p>
        <p class="text-xs mt-1">在地图上点选位置，分享你在城市中的第一份体感吧！</p>
      </div>

      <div v-else class="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        <div
          v-for="record in records"
          :key="record.check_in_id"
          class="rounded-xl border border-line bg-canvas p-4 transition hover:border-accent"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-2">
              <span class="sensation-label" :class="`label-${record.thermal_sensation}`">
                <span class="sensation-dot mr-1" :class="`sensation-${record.thermal_sensation}`" />
                {{ sensationNames[record.thermal_sensation] }}
              </span>
              <span class="text-xs text-muted">
                {{ record.setting === 'indoor' ? '室内' : record.setting === 'outdoor' ? '室外' : '室内外混合' }}
              </span>
              <span class="text-xs rounded bg-white px-2 py-0.5 border border-line text-muted">
                修订号: r{{ record.revision }}
              </span>
            </div>
            <div class="flex items-center gap-1.5">
              <button class="button text-xs py-1 px-2.5" @click="emit('edit', record)">
                编辑
              </button>
              <button
                class="button text-xs py-1 px-2.5 text-terracotta"
                :disabled="deletingId === record.check_in_id"
                @click="handleDelete(record)"
              >
                {{ deletingId === record.check_in_id ? '删除中' : '删除' }}
              </button>
            </div>
          </div>

          <p class="mt-2.5 text-sm leading-relaxed text-ink">
            {{ record.note || '（未填写补充文字说明）' }}
          </p>

          <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted border-t border-line/60 pt-2.5">
            <span>体验时间：{{ localTime(record.experienced_at, true) }}</span>
            <span>坐标：{{ record.location.coordinates[0].toFixed(4) }}, {{ record.location.coordinates[1].toFixed(4) }}</span>
            <span class="ml-auto font-medium text-accent">
              气象匹配：{{ matchNames[record.match_status] }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </AppDialog>
</template>
