// Positions highlight boxes over the document preview and handles action buttons.
(function () {
  "use strict";
  var wrap = document.getElementById("overlay-wrap");
  if (wrap) {
    var width = parseFloat(wrap.dataset.width);
    var height = parseFloat(wrap.dataset.height);
    // Box coordinates are in original-image pixels; convert to percentages so the overlay
    // scales with the displayed image.
    wrap.querySelectorAll(".hl").forEach(function (box) {
      box.style.left = (parseFloat(box.dataset.x) / width) * 100 + "%";
      box.style.top = (parseFloat(box.dataset.y) / height) * 100 + "%";
      box.style.width = (parseFloat(box.dataset.w) / width) * 100 + "%";
      box.style.height = (parseFloat(box.dataset.h) / height) * 100 + "%";
    });
    var toggle = document.getElementById("toggle-highlights");
    if (toggle) {
      toggle.addEventListener("change", function () {
        wrap.classList.toggle("hide-highlights", !toggle.checked);
      });
    }
  }

  var verifyForm = document.getElementById("verify-form");
  if (verifyForm) {
    verifyForm.addEventListener("submit", function () {
      var button = document.getElementById("verify-button");
      button.disabled = true;
      button.textContent = "Verifying…";
      document.getElementById("verify-progress").hidden = false;
    });
  }

  var deleteForm = document.getElementById("delete-form");
  if (deleteForm) {
    deleteForm.addEventListener("submit", function (event) {
      if (!window.confirm("Delete this document, its image, extracted text and result permanently?")) {
        event.preventDefault();
      }
    });
  }
})();
