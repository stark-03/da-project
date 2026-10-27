// Client-side preview and early checks. The server re-validates everything.
(function () {
  "use strict";
  var form = document.getElementById("upload-form");
  if (!form) return;
  var input = form.querySelector('input[type="file"]');
  var img = document.getElementById("preview-image");
  var empty = document.getElementById("preview-empty");
  var meta = document.getElementById("preview-meta");
  var error = document.getElementById("client-error");
  var submit = document.getElementById("upload-submit");
  var maxBytes = parseInt(form.dataset.maxBytes, 10);
  var allowed = (form.dataset.allowed || "").split(",");
  var objectUrl = null;

  function showError(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  function reset() {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    img.hidden = true;
    img.removeAttribute("src");
    empty.hidden = false;
    meta.textContent = "";
  }

  input.addEventListener("change", function () {
    showError("");
    reset();
    var file = input.files && input.files[0];
    if (!file) return;
    var ext = (file.name.split(".").pop() || "").toLowerCase();
    if (allowed.indexOf(ext) === -1) {
      showError("Unsupported file type. Allowed: " + allowed.join(", ").toUpperCase() + ".");
      return;
    }
    if (file.size > maxBytes) {
      showError("File is too large (" + (file.size / 1048576).toFixed(1) + " MB). Maximum is " + Math.round(maxBytes / 1048576) + " MB.");
      return;
    }
    objectUrl = URL.createObjectURL(file);
    img.onload = function () {
      meta.textContent = file.name + " · " + img.naturalWidth + "×" + img.naturalHeight + " px · " + (file.size / 1024).toFixed(0) + " KB";
    };
    img.onerror = function () {
      reset();
      showError("This file could not be displayed as an image. It may be corrupted.");
    };
    img.src = objectUrl;
    img.hidden = false;
    empty.hidden = true;
  });

  form.addEventListener("submit", function (event) {
    if (!error.hidden) {
      event.preventDefault();
      return;
    }
    submit.disabled = true;
    submit.value = "Uploading…";
  });
})();
