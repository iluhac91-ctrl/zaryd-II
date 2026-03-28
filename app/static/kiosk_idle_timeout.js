(function () {
  const TIMEOUT_MS = 5000;
  const REDIRECT_URL = "/";
  let timer = null;

  function resetTimer() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      window.location.href = REDIRECT_URL;
    }, TIMEOUT_MS);
  }

  ["click","touchstart","touchmove","mousemove","keydown","scroll"].forEach(function (eventName) {
    window.addEventListener(eventName, resetTimer, { passive: true });
  });

  resetTimer();
})();
