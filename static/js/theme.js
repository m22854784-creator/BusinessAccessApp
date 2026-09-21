/* Dark mode: runs in <head> before first paint so there is no flash. */
(function () {
  var KEY = "bams-theme";
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-theme-toggle]")) return;
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(KEY, next); } catch (err) {}
  });
})();
