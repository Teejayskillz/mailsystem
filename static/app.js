/* Small, dependency-free enhancements. All inline event handlers are avoided
   so the Content-Security-Policy can stay strict (script-src 'self'). */
(function () {
    "use strict";

    function flash(text) {
        var region = document.getElementById("mailgen-toast");
        if (!region) {
            region = document.createElement("div");
            region.id = "mailgen-toast";
            region.className = "position-fixed bottom-0 end-0 p-3";
            region.style.zIndex = "1080";
            document.body.appendChild(region);
        }
        var toast = document.createElement("div");
        toast.className = "alert alert-success shadow-sm mb-2";
        toast.textContent = text;
        region.appendChild(toast);
        window.setTimeout(function () {
            toast.remove();
        }, 2200);
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            var area = document.createElement("textarea");
            area.value = text;
            area.setAttribute("readonly", "");
            area.style.position = "fixed";
            area.style.opacity = "0";
            document.body.appendChild(area);
            area.select();
            var ok = false;
            try {
                ok = document.execCommand("copy");
            } catch (e) {
                ok = false;
            }
            area.remove();
            return ok;
        }
    }

    document.addEventListener("click", function (event) {
        var button = event.target.closest("[data-copy]");
        if (!button) {
            return;
        }
        event.preventDefault();
        copyText(button.getAttribute("data-copy")).then(function (ok) {
            flash(ok ? "Copied to clipboard" : "Copy failed — select the address manually");
        });
    });

    document.addEventListener("submit", function (event) {
        var form = event.target;
        var message = form.getAttribute("data-confirm");
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    function resizeFrame(frame) {
        try {
            var doc = frame.contentDocument;
            if (doc && doc.documentElement) {
                var height = Math.max(doc.documentElement.scrollHeight, window.innerHeight * 0.62);
                frame.style.height = height + 24 + "px";
            }
        } catch (e) {
            /* cross-origin or not ready: keep the CSS min-height */
        }
    }

    function bindFrames() {
        document.querySelectorAll("iframe[data-autoheight]").forEach(function (frame) {
            frame.addEventListener("load", function () {
                resizeFrame(frame);
            });
            if (frame.contentDocument && frame.contentDocument.readyState === "complete") {
                resizeFrame(frame);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindFrames);
    } else {
        bindFrames();
    }
})();
