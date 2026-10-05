"""Минимальный AbortController и поддельный fetch для JS-обвязок семейств frontend.

В vm-контексте песочницы нет AbortController и fetch; здесь — совместимая по смыслу
реализация: signal.aborted, signal.addEventListener('abort', fn), abort() один раз.
"""

FAKE_ABORT = """class AbortController {
  constructor() {
    const listeners = [];
    this.signal = { aborted: false, addEventListener: (type, fn) => listeners.push(fn) };
    this._fire = () => listeners.forEach((fn) => fn());
  }
  abort() {
    if (this.signal.aborted) return;
    this.signal.aborted = true;
    this._fire();
  }
}
function abortError() { const e = new Error('aborted'); e.name = 'AbortError'; return e; }
function makeFetch(plan) {
  const api = { aborted: 0, completed: 0, started: 0 };
  api.fetch = (id, opts = {}) => new Promise((resolve, reject) => {
    const signal = opts.signal;
    api.started += 1;
    if (signal && signal.aborted) { api.aborted += 1; reject(abortError()); return; }
    const t = setTimeout(() => {
      api.completed += 1;
      if (plan[id].fail) reject(new Error('HTTP 500')); else resolve('data-' + id);
    }, plan[id].ms);
    if (signal) signal.addEventListener('abort', () => { clearTimeout(t); api.aborted += 1; reject(abortError()); });
  });
  return api;
}"""
