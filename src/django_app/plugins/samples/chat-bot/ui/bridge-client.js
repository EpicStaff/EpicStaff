// EpicStaff plugin bridge client, version 1. Copy it into any plugin page as a classic script.
// EpicStaff.ready -> Promise<context>; EpicStaff.call(method, params) -> Promise<result>;
// EpicStaff.on(topic, handler(data, subscription)) for 'session.message', 'session.status',
// 'subscription.closed'.
(function () {
  'use strict';

  var BRIDGE_VERSION = 1;
  var port = null;
  var nextId = 1;
  var pending = Object.create(null);
  var handlers = Object.create(null);
  var resolveReady;
  var rejectReady;
  var ready = new Promise(function (resolve, reject) {
    resolveReady = resolve;
    rejectReady = reject;
  });

  function bridgeError(error) {
    var result = new Error((error && error.message) || 'The bridge call failed.');
    result.code = (error && error.code) || 'internal';
    return result;
  }

  function onWindowMessage(event) {
    // Only the embedding EpicStaff page, only once, and only a message carrying the port.
    if (port || event.source !== window.parent) return;
    var data = event.data;
    if (!data || data.v !== BRIDGE_VERSION) return;
    if (data.kind === 'error') {
      rejectReady(bridgeError(data.error));
      return;
    }
    if (data.kind !== 'init' || !event.ports || event.ports.length !== 1) return;
    window.removeEventListener('message', onWindowMessage);
    port = event.ports[0];
    port.onmessage = onPortMessage;
    resolveReady(data.context);
  }

  function onPortMessage(event) {
    var message = event.data;
    if (!message || message.v !== BRIDGE_VERSION) return;
    if (message.kind === 'response' && pending[message.id]) {
      var request = pending[message.id];
      delete pending[message.id];
      if (message.ok) request.resolve(message.result);
      else request.reject(bridgeError(message.error));
    } else if (message.kind === 'event') {
      (handlers[message.topic] || []).forEach(function (handler) {
        handler(message.data, message.subscription);
      });
    }
  }

  function call(method, params) {
    return ready.then(function () {
      return new Promise(function (resolve, reject) {
        var id = nextId++;
        pending[id] = { resolve: resolve, reject: reject };
        port.postMessage({ v: BRIDGE_VERSION, kind: 'request', id: id, method: method, params: params || {} });
      });
    });
  }

  function on(topic, handler) {
    (handlers[topic] = handlers[topic] || []).push(handler);
  }

  window.addEventListener('message', onWindowMessage);
  window.parent.postMessage({ v: BRIDGE_VERSION, kind: 'ready' }, '*');
  window.EpicStaff = { ready: ready, call: call, on: on };
})();
