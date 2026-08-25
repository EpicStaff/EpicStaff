(function () {
  "use strict";

  // Capture basePath synchronously — document.currentScript is null after any async callback
  var currentScript = document.currentScript;
  if (!currentScript) {
    console.error("[epic-chat] embed.js must be loaded as a classic <script> tag, not as an ES module");
    return;
  }

  // Derive base path from the URL of this script itself:
  // https://cdn.example.com/v1.2.3/embed.js  →  https://cdn.example.com/v1.2.3/
  var scriptSrc = currentScript.src;
  var basePath = scriptSrc.substring(0, scriptSrc.lastIndexOf("/") + 1);

  // Guard against double-loading (idempotent embed snippet)
  if (window.__epicChatEmbedLoaded) {
    return;
  }
  window.__epicChatEmbedLoaded = true;

  // Expose basePath so the Angular widget can resolve image assets at runtime.
  // asset.utils.ts reads window.__epicChatBasePath as a fallback when no basePath
  // @Input() is provided on <epic-chat>.
  window.__epicChatBasePath = basePath;

  // Load styles.css at document level (not inside Shadow DOM) so @font-face
  // declarations are registered globally — Shadow DOM inherits font metrics
  // but @font-face must be defined in the light-DOM stylesheet.
  var link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = basePath + "styles.css";
  document.head.appendChild(link);

  // Load main.js directly — the widget is zoneless, so there is no zone.js
  // polyfill step anymore (one fewer sequential request before bootstrap).
  var main = document.createElement("script");
  main.type = "module";
  main.src = basePath + "main.js";

  main.onerror = function () {
    console.error("[epic-chat] Failed to load main.js from " + basePath);
  };

  document.head.appendChild(main);
})();
