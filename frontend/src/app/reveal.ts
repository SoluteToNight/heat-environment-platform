import type { Directive } from 'vue';

// 滚动进入视口后淡入上移；prefers-reduced-motion 下由全局 CSS 立即显示
let observer: IntersectionObserver | null = null;
function getObserver() {
  if (typeof IntersectionObserver === 'undefined') return null;
  observer ||= new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer?.unobserve(entry.target);
      }
    }
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  return observer;
}

export const vReveal: Directive<HTMLElement, number | undefined> = {
  mounted(el, binding) {
    el.classList.add('reveal');
    if (binding.value) el.style.transitionDelay = `${binding.value}ms`;
    const io = getObserver();
    if (io) io.observe(el);
    else el.classList.add('is-visible');
  },
  unmounted(el) {
    observer?.unobserve(el);
  },
};
