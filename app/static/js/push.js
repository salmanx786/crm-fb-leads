/* Web Push opt-in for the MC admin dashboard.
 *
 * Drives the browser side of enabling notifications:
 *   1. register the service worker (/dashboard/sw.js),
 *   2. ask for notification permission,
 *   3. create a PushManager subscription with the VAPID public key,
 *   4. POST it to /dashboard/push/subscribe (CSRF token in the X-CSRFToken
 *      header, read from the <meta name="csrf-token"> tag).
 * Unsubscribe reverses steps 3–4 via /dashboard/push/unsubscribe.
 *
 * The settings page wires the buttons by id: #push-enable, #push-disable, and
 * a #push-status line. The VAPID public key is read from #push-enable's
 * data-vapid-key attribute.
 */
(function () {
  "use strict";

  var statusEl = document.getElementById("push-status");
  var enableBtn = document.getElementById("push-enable");
  var disableBtn = document.getElementById("push-disable");
  if (!enableBtn) return; // not on the notifications page

  var SW_URL = "/dashboard/sw.js";
  var SUBSCRIBE_URL = "/dashboard/push/subscribe";
  var UNSUBSCRIBE_URL = "/dashboard/push/unsubscribe";

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  function csrfToken() {
    var tag = document.querySelector('meta[name="csrf-token"]');
    return tag ? tag.getAttribute("content") : "";
  }

  // VAPID public keys are base64url; PushManager needs a Uint8Array.
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = window.atob(base64);
    var output = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; ++i) output[i] = raw.charCodeAt(i);
    return output;
  }

  function supported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
  }

  function register() {
    return navigator.serviceWorker.register(SW_URL, { scope: "/dashboard/" });
  }

  function enable() {
    if (!supported()) {
      setStatus("This browser doesn't support push notifications.");
      return;
    }
    var vapidKey = enableBtn.getAttribute("data-vapid-key");
    if (!vapidKey) {
      setStatus("Push isn't configured yet — save a VAPID key pair first.");
      return;
    }

    setStatus("Requesting permission…");
    Notification.requestPermission()
      .then(function (permission) {
        if (permission !== "granted") {
          throw new Error("Notifications were blocked in the browser.");
        }
        return register();
      })
      .then(function (registration) {
        return registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidKey),
        });
      })
      .then(function (subscription) {
        return post(SUBSCRIBE_URL, { subscription: subscription.toJSON() });
      })
      .then(function (res) {
        if (!res.ok) throw new Error("Server rejected the subscription.");
        setStatus("Notifications enabled on this browser.");
      })
      .catch(function (err) {
        setStatus(err.message || "Could not enable notifications.");
      });
  }

  function disable() {
    if (!supported()) return;
    setStatus("Disabling…");
    navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (!subscription) {
          setStatus("Notifications are not enabled on this browser.");
          return null;
        }
        var endpoint = subscription.endpoint;
        return subscription.unsubscribe().then(function () {
          return post(UNSUBSCRIBE_URL, { endpoint: endpoint });
        });
      })
      .then(function (res) {
        if (res) setStatus("Notifications disabled on this browser.");
      })
      .catch(function () {
        setStatus("Could not disable notifications.");
      });
  }

  enableBtn.addEventListener("click", enable);
  if (disableBtn) disableBtn.addEventListener("click", disable);

  // Reflect current permission state on load.
  if (supported() && Notification.permission === "denied") {
    setStatus("Notifications are blocked in this browser's site settings.");
  }
})();
