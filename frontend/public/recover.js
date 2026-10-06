/* Страховка от пустой страницы после выкладки (обычный скрипт, до сборки приложения).
 * Если файл сборки не загрузился (вкладка или кэш держат index.html прежней версии, а файлы уже заменены)
 * или приложение так и не отрисовалось — снимаем service worker, чистим кэши и перезагружаем страницу один раз. */
(function () {
  var KEY = "fsp_recover_at";
  function recover() {
    try {
      var last = Number(sessionStorage.getItem(KEY)) || 0;
      if (Date.now() - last < 5 * 60 * 1000) return; // не чаще раза в 5 минут — без циклов перезагрузки
      sessionStorage.setItem(KEY, String(Date.now()));
    } catch (e) { return; }
    var jobs = [];
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      jobs.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
        return Promise.all(rs.map(function (r) { return r.unregister(); }));
      }));
    }
    if (window.caches && caches.keys) {
      jobs.push(caches.keys().then(function (ks) { return Promise.all(ks.map(function (k) { return caches.delete(k); })); }));
    }
    Promise.all(jobs).catch(function () { return null; }).then(function () { location.reload(); });
  }
  window.__fspRecover = recover;
  window.addEventListener("error", function (e) {
    var t = e.target;
    if (!t || t === window || (t.tagName !== "SCRIPT" && t.tagName !== "LINK")) return;
    if (/\/assets\//.test(t.src || t.href || "")) recover();
  }, true);
  window.addEventListener("vite:preloadError", recover);
  window.addEventListener("load", function () {
    setTimeout(function () {
      var root = document.getElementById("root");
      if (root && !root.firstChild && navigator.onLine !== false) recover();
    }, 12000);
  });
})();
