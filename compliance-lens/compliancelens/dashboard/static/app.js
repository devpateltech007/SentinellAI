// ComplianceLens dashboard: the few things a page does by itself. Everything also works
// without JavaScript (forms post, the progress panel has a Refresh link).
(function () {
  "use strict";

  // Live audit progress: while an audit runs, swap in the panel from /run/progress.
  function poll() {
    var panel = document.getElementById("progress");
    if (!panel || panel.dataset.active !== "1") return;
    window.setTimeout(function () {
      fetch(panel.dataset.poll, { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok || response.redirected) throw new Error("signed out or gone");
          return response.text();
        })
        .then(function (html) {
          var holder = document.createElement("template");
          holder.innerHTML = html.trim();
          var fresh = holder.content.firstElementChild;
          if (!fresh || fresh.id !== "progress") throw new Error("unexpected reply");
          panel.replaceWith(fresh);
          if (fresh.dataset.active !== "1") {
            var button = document.querySelector("form[action='/run'] button[type=submit]");
            if (button) button.disabled = false;
          }
          poll();
        })
        .catch(function () {
          panel.dataset.active = "0"; // stop; the Refresh link still works
        });
    }, 1000);
  }

  // Filters apply as soon as a choice changes.
  document.querySelectorAll("form[data-autosubmit] select").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  // One click, one submission (the server refuses a second one anyway).
  document.querySelectorAll("form[method=post]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.sent === "1") { event.preventDefault(); return; }
      form.dataset.sent = "1";
    });
  });

  poll();
})();
