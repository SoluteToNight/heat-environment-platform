<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import AppDialog from '../../components/AppDialog.vue';
import AppIcon from '../../components/AppIcon.vue';
import { api, ApiError, errorMessage } from '../../services/api';
import type { CheckIn, CheckInBody, Coordinates, Sensation } from '../../services/contracts';
import { datetimeLocal, matchNames, publicGrid, sensationNames } from '../../services/format';
import { useWorkspace } from '../../stores/workspace';
const props = defineProps<{ open: boolean; coordinates: Coordinates | null; editing: CheckIn | null }>();
const emit = defineEmits<{ close: []; pick: []; login: []; saved: []; preview: [point: Coordinates, coarse: boolean] }>();
const store = useWorkspace();
const draft = reactive({ longitude: '' as string | number, latitude: '' as string | number, experienced: datetimeLocal(), sensation: '' as Sensation | '', comfort: '', setting: 'unknown', activity: '', sun: '', note: '', visibility: '', precision: 'grid_200m', confirmed: false });
const baseline = ref('');
const error = ref('');
const saved = ref('');
const submitting = ref(false);
const discard = ref(false);
const conflict = ref(false);
const latest = ref<CheckIn | null>(null);
let key = '';
let lastBody = '';
let locationSource: CheckInBody['location_source'] = 'manual_coordinates';
let accuracy: number | null = null;
const dirty = computed(() => !!baseline.value && baseline.value !== JSON.stringify(draft));
const coordinates = computed<Coordinates | null>(() => {
  const longitude = Number(draft.longitude); const latitude = Number(draft.latitude);
  return draft.longitude !== '' && draft.latitude !== '' && Number.isFinite(longitude) && Number.isFinite(latitude) && longitude >= -180 && longitude <= 180 && latitude >= -90 && latitude <= 90 ? [longitude, latitude] : null;
});
const grid = computed(() => coordinates.value && draft.visibility === 'public' && draft.precision === 'grid_200m' ? publicGrid(coordinates.value) : null);
function initialize() {
  const record = props.editing;
  const point = record?.location.coordinates || props.coordinates;
  Object.assign(draft, { longitude: point?.[0] ?? '', latitude: point?.[1] ?? '', experienced: datetimeLocal(record?.experienced_at), sensation: record?.thermal_sensation || '', comfort: record?.thermal_comfort || '', setting: record?.setting || 'unknown', activity: record?.activity || '', sun: record?.sun_exposure || '', note: record?.note || '', visibility: record?.visibility || '', precision: record?.public_location_precision || 'grid_200m', confirmed: false });
  locationSource = record?.location_source || (props.coordinates ? 'manual_map' : 'manual_coordinates'); accuracy = record?.horizontal_accuracy_m ?? null;
  baseline.value = JSON.stringify(draft); key = ''; lastBody = ''; error.value = ''; saved.value = ''; discard.value = false; conflict.value = false; latest.value = null;
}
watch(() => props.open, open => { if (open && !dirty.value) initialize(); });
watch(() => props.editing?.check_in_id, initialize);
watch(() => props.coordinates, point => { if (point) { draft.longitude = point[0]; draft.latitude = point[1]; locationSource = 'manual_map'; accuracy = null; } });
watch([coordinates, () => draft.visibility, () => draft.precision], () => { if (coordinates.value) emit('preview', coordinates.value, !!grid.value); });
function requestClose() { if (submitting.value) return; if (dirty.value && !saved.value) discard.value = true; else emit('close'); }
function discardDraft() { baseline.value = ''; initialize(); emit('close'); }
async function locate() {
  if (!navigator.geolocation) { error.value = '此浏览器不支持定位，请在地图选点或输入坐标。'; return; }
  navigator.geolocation.getCurrentPosition(position => {
    draft.longitude = position.coords.longitude; draft.latitude = position.coords.latitude;
    locationSource = 'browser_geolocation'; accuracy = position.coords.accuracy;
  }, () => { error.value = '未获得定位权限，请在地图选点或输入坐标。'; }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
}
async function submit() {
  error.value = ''; saved.value = '';
  if (!coordinates.value) { error.value = '请填写合法经纬度，或在地图上选择地点。'; return; }
  const bbox = store.scene?.bbox;
  if (bbox && (coordinates.value[0] < bbox[0] || coordinates.value[0] > bbox[2] || coordinates.value[1] < bbox[1] || coordinates.value[1] > bbox[3])) { error.value = '地点超出当前场景范围，请重新选点。'; return; }
  if (!draft.sensation) { error.value = '请选择本次体验的冷热感觉。'; return; }
  if (!draft.visibility) { error.value = '请选择记录的公开范围。'; return; }
  if (draft.visibility === 'public' && !draft.confirmed) { error.value = '请确认公开位置精度。'; return; }
  const experienced = new Date(`${draft.experienced}:00+08:00`);
  if (!Number.isFinite(experienced.getTime()) || experienced.getTime() > Date.now() + 300000) { error.value = '体验时间不能晚于当前时间，请检查上海时间。'; return; }
  if (!store.session.authenticated) { emit('login'); return; }
  const body: CheckInBody = { scene_id: store.scene!.scene_id, location: { type: 'Point', coordinates: coordinates.value }, location_source: locationSource, horizontal_accuracy_m: accuracy, experienced_at: experienced.toISOString(), time_source: 'user_selected', time_uncertainty_minutes: null, thermal_sensation: draft.sensation, thermal_comfort: (draft.comfort || null) as CheckInBody['thermal_comfort'], setting: draft.setting as CheckInBody['setting'], activity: draft.activity || null, sun_exposure: draft.sun || null, note: draft.note || null, visibility: draft.visibility as CheckInBody['visibility'], public_location_precision: draft.visibility === 'public' ? draft.precision as 'exact' | 'grid_200m' : null };
  const serialized = JSON.stringify(body);
  if (lastBody !== serialized || !key) { key = crypto.randomUUID(); lastBody = serialized; }
  submitting.value = true;
  try {
    const record = props.editing ? await api.edit(props.editing.check_in_id, body, props.editing.revision) : await api.create(body, key);
    saved.value = `${store.isDemo ? '已保存在当前演示会话' : '记录已保存'} · ${matchNames[record.match_status]}`;
    baseline.value = JSON.stringify(draft); emit('saved');
  } catch (problem) {
    error.value = errorMessage(problem);
    if (problem instanceof ApiError && problem.status === 401) { store.session = { authenticated: false, user: null }; emit('login'); }
    if (problem instanceof ApiError && problem.status === 412) conflict.value = true;
  } finally { submitting.value = false; }
}
async function compareLatest() {
  try { latest.value = (await api.myRecords()).items.find(record => record.check_in_id === props.editing?.check_in_id) || null; }
  catch (problem) { error.value = errorMessage(problem); }
}
const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty.value) event.preventDefault(); };
window.addEventListener('beforeunload', beforeUnload);
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload));
defineExpose({ reset: () => { baseline.value = ''; initialize(); }, isDirty: () => dirty.value, requestClose });
</script>
<template>
  <AppDialog :open="open" :title="editing ? '编辑体感记录' : '记录此刻的感受'" wide @close="requestClose">
    <div v-if="discard" class="mb-5 rounded-xl bg-amber-50 p-4"><p class="text-sm">还有未保存的修改，是否放弃？</p><div class="mt-3 flex gap-2"><button class="button" @click="discard = false">继续编辑</button><button class="button text-red-700" @click="discardDraft">放弃草稿</button></div></div>
    <div v-if="saved" class="space-y-5 py-5 text-center" role="status"><div class="mx-auto grid size-14 place-items-center rounded-full bg-green-soft text-accent"><AppIcon name="check" :size="26" /></div><h3 class="text-lg font-semibold">谢谢你分享城市里的温度</h3><p class="text-sm text-muted">{{ saved }}</p><button class="button-primary mx-auto" @click="emit('close')">完成</button></div>
    <form v-else class="space-y-7" @submit.prevent="submit">
      <section><div class="mb-4 flex items-center gap-3"><span class="step">01</span><h3 class="section-title">地点与时间</h3></div><div class="grid grid-cols-2 gap-3"><button type="button" class="button justify-center" @click="emit('pick')"><AppIcon name="pin" />地图选点</button><button type="button" class="button justify-center" @click="locate"><AppIcon name="locate" />使用定位</button></div><div class="mt-4 grid grid-cols-2 gap-3"><label class="field-label">经度<input v-model="draft.longitude" class="input" type="number" min="-180" max="180" step="any" required @input="locationSource = 'manual_coordinates'; accuracy = null" /></label><label class="field-label">纬度<input v-model="draft.latitude" class="input" type="number" min="-90" max="90" step="any" required @input="locationSource = 'manual_coordinates'; accuracy = null" /></label></div><label class="field-label mt-4">体验时间 · 上海<input v-model="draft.experienced" class="input" type="datetime-local" required /></label><p class="mt-2 text-xs text-muted">记录实际体验时间，与地图预报时刻独立。</p></section>
      <section><div class="mb-4 flex items-center gap-3"><span class="step">02</span><h3 class="section-title">你的体感</h3></div><fieldset><legend class="field-label mb-3">冷热感觉 <span class="text-terracotta">*</span></legend><div class="grid grid-cols-5 gap-2"><button v-for="(label, value) in sensationNames" :key="value" type="button" class="sensation-button" :class="draft.sensation === value ? 'ring-2 ring-accent bg-green-soft!' : ''" :aria-pressed="draft.sensation === value" @click="draft.sensation = value"><span class="sensation-dot" :class="`sensation-${value}`" />{{ label }}</button></div></fieldset><div class="mt-5 grid grid-cols-2 gap-4"><label class="field-label">舒适程度<select v-model="draft.comfort" class="input"><option value="">不填写</option><option value="comfortable">舒适</option><option value="ordinary">一般</option><option value="uncomfortable">不舒适</option></select></label><label class="field-label">所在环境<select v-model="draft.setting" class="input"><option value="unknown">未确定</option><option value="outdoor">室外</option><option value="indoor">室内</option><option value="mixed">室内外混合</option></select></label><label class="field-label">活动<select v-model="draft.activity" class="input"><option value="">不填写</option><option value="walking">步行</option><option value="resting">休息</option><option value="exercising">运动</option><option value="commuting">通勤</option></select></label><label class="field-label">日晒情况<select v-model="draft.sun" class="input"><option value="">不填写</option><option value="sun">阳光直晒</option><option value="shade">阴影中</option><option value="mixed">时晒时阴</option></select></label></div></section>
      <section><div class="mb-4 flex items-center gap-3"><span class="step">03</span><h3 class="section-title">补充与公开范围</h3></div><label class="field-label">想补充些什么？<textarea v-model="draft.note" class="input min-h-24 resize-y" maxlength="1000" placeholder="例如：树荫下有风，走起来舒服一些。" /></label><p class="mt-1 text-right text-xs text-muted">{{ draft.note.length }} / 1000</p><fieldset class="mt-4"><legend class="field-label mb-2">谁可以看到 <span class="text-terracotta">*</span></legend><div class="flex gap-4"><label class="flex min-h-11 items-center gap-2 text-sm"><input v-model="draft.visibility" type="radio" value="private" name="visibility" />仅自己</label><label class="flex min-h-11 items-center gap-2 text-sm"><input v-model="draft.visibility" type="radio" value="public" name="visibility" />公开分享</label></div></fieldset>
        <div v-if="draft.visibility === 'public'" class="mt-3 rounded-xl border border-line bg-canvas p-4"><label class="field-label">公开位置<select v-model="draft.precision" class="input" @change="draft.confirmed = false"><option value="grid_200m">约 200 米网格中心</option><option value="exact">精确位置</option></select></label><div v-if="grid" class="mt-3 flex gap-3"><svg viewBox="0 0 80 80" class="size-16 shrink-0" role="img" aria-label="公开网格示意，标记位于中心"><path d="M0 0H80V80H0Z" fill="#e1eee5"/><path d="M0 0V80M40 0V80M80 0V80M0 0H80M0 40H80M0 80H80" stroke="#9ab8a5" stroke-dasharray="3 3"/><circle cx="40" cy="40" r="6" fill="#176c53" stroke="white" stroke-width="2"/></svg><p class="text-xs leading-6 text-muted">公开标记位于网格中心<br />{{ grid.center[0].toFixed(5) }}, {{ grid.center[1].toFixed(5) }}<br />粗化位置不保证匿名。</p></div><label class="mt-3 flex items-start gap-2 text-xs leading-6"><input v-model="draft.confirmed" type="checkbox" class="mt-1.5" />我确认以{{ draft.precision === 'exact' ? '精确位置' : '200 米网格中心' }}公开这条记录。</label></div>
      </section>
      <div v-if="error" class="status-warning" role="alert">{{ error }}<button v-if="conflict" type="button" class="text-button block" @click="compareLatest">加载最新版本以比较</button><div v-if="latest" class="mt-2 border-t border-amber-200 pt-2"><p>最新记录：{{ latest.note || '无补充' }}</p><p>本地修改仍在表单中。关闭并重新编辑记录可使用最新修订。</p></div></div>
      <div class="sticky -bottom-6 -mx-6 flex items-center justify-between gap-3 border-t border-line bg-white px-6 py-4"><p class="text-xs text-muted">{{ store.isDemo ? '演示记录仅保存在本次会话' : '你的体验，让城市温度更完整' }}</p><button class="button-primary shrink-0" :disabled="submitting || conflict" type="submit"><span v-if="submitting" class="loader size-4 border-white/30 border-t-white" />{{ submitting ? '保存中' : store.session.authenticated ? '保存记录' : '登录并保存' }}<AppIcon name="next" :size="16" /></button></div>
    </form>
  </AppDialog>
</template>
