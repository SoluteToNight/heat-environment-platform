<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
const props = defineProps<{ open: boolean; title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
let previous: HTMLElement | null = null;
watch(() => props.open, async value => {
  await nextTick();
  if (value && !dialog.value?.open) { previous = document.activeElement as HTMLElement; dialog.value?.showModal(); }
  else if (!value && dialog.value?.open) { dialog.value.close(); previous?.focus(); }
}, { immediate: true });
onBeforeUnmount(() => { if (dialog.value?.open) { dialog.value.close(); previous?.focus(); } });
</script>
<template>
  <dialog ref="dialog" :aria-label="title" class="app-dialog" :class="wide ? 'max-w-2xl' : 'max-w-lg'" @cancel.prevent="emit('close')" @click="event => { if (event.target === dialog) emit('close'); }">
    <div class="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white px-6 py-4">
      <h2 class="text-lg font-semibold">{{ title }}</h2><button class="icon-button" aria-label="关闭对话框" @click="emit('close')"><AppIcon name="close" /></button>
    </div>
    <div class="p-6"><slot /></div>
  </dialog>
</template>
