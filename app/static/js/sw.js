/* Push service worker for the MC admin dashboard.
 *
 * Served from /dashboard/sw.js so its control scope covers the admin area.
 * It has two jobs:
 *   - `push`: render the notification the server sent (title/body/url).
 *   - `notificationclick`: focus an already-open dashboard tab, or open the
 *     lead's page if none is open.
 * The payload shape is what push_service._dispatch sends:
 *   {"title": ..., "body": ..., "url": ...}  (url optional)
 */

self.addEventListener("push", function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "New notification", body: event.data ? event.data.text() : "" };
  }

  var title = data.title || "New lead";
  var options = {
    body: data.body || "",
    icon: "/static/img/favicon.svg",
    badge: "/static/img/favicon.svg",
    data: { url: data.url || "/dashboard/leads" },
    tag: "mc-lead", // coalesce bursts so admins aren't flooded
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/dashboard/leads";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windowClients) {
      // Focus an existing dashboard tab and navigate it to the lead if possible.
      for (var i = 0; i < windowClients.length; i++) {
        var client = windowClients[i];
        if (client.url.indexOf("/dashboard") !== -1 && "focus" in client) {
          if ("navigate" in client) {
            client.navigate(target);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(target);
      }
    })
  );
});
