(function () {
  var buttons = document.querySelectorAll("[data-set-lang]");
  var nodes = document.querySelectorAll("[data-lang]");
  function setLang(lang) {
    document.documentElement.lang = lang;
    nodes.forEach(function (el) {
      el.hidden = el.getAttribute("data-lang") !== lang;
    });
    buttons.forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-set-lang") === lang ? "true" : "false");
    });
    try { localStorage.setItem("mb-lang", lang); } catch (e) {}
  }
  var start = "en";
  try { start = localStorage.getItem("mb-lang") || start; } catch (e) {}
  var q = new URLSearchParams(location.search).get("lang");
  if (q && /^(en|zh|ja|ko)$/.test(q)) start = q;
  setLang(start);
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () { setLang(btn.getAttribute("data-set-lang")); });
  });
})();
