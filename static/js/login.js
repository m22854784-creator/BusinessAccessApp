(function () {
  var form = document.getElementById("login-form");
  var errBox = document.getElementById("login-error");
  var btn = document.getElementById("login-btn");
  var tabs = document.querySelectorAll("[data-type]");
  var type = form.dataset.type;
  var csrf = document.querySelector('meta[name="csrf-token"]').content;

  function setType(t) {
    type = t;
    tabs.forEach(function (b) { b.setAttribute("aria-selected", b.dataset.type === t ? "true" : "false"); });
    history.replaceState(null, "", "?type=" + t);
    errBox.hidden = true;
  }
  tabs.forEach(function (b) { if (b.tagName === "BUTTON") b.addEventListener("click", function () { setType(b.dataset.type); }); });

  var pw = form.elements.password, toggle = document.getElementById("pw-toggle");
  toggle.addEventListener("click", function () {
    var show = pw.type === "password";
    pw.type = show ? "text" : "password";
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    errBox.hidden = true;
    btn.disabled = true; btn.textContent = "Signing in...";
    fetch("/api/login", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ username: form.elements.username.value, password: pw.value, login_type: type })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { res: res, data: data }; });
    }).then(function (r) {
      if (r.res.ok) { location.href = r.data.redirect || "/app"; return; }
      if (r.data.code === "CSRF") { location.reload(); return; }
      errBox.textContent = r.data.error || "Sign in failed. Try again.";
      errBox.hidden = false;
      pw.value = ""; pw.focus();
    }).catch(function () {
      errBox.textContent = "Cannot reach the server. Check your connection and try again.";
      errBox.hidden = false;
    }).then(function () { btn.disabled = false; btn.textContent = "Sign in"; });
  });
})();
