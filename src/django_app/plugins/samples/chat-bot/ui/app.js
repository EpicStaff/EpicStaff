// Chat Bot page. Each question runs the plugin's "chat" flow through the EpicStaff bridge and
// shows the flow's answer. The conversation lives only in memory (the sandbox has no storage).
(function () {
  'use strict';

  var MAX_QUESTION_LENGTH = 4000;
  var MAX_HISTORY_TURNS = 10;
  var FAILED_STATUSES = { error: true, stop: true, expired: true };

  var messagesElement = document.getElementById('messages');
  var questionElement = document.getElementById('question');
  var sendButton = document.getElementById('send');
  var statusElement = document.getElementById('status');

  var history = [];
  var turn = null; // { question, subscription, pendingElement, answered }

  function setStatus(text) {
    statusElement.textContent = text || '';
  }

  function setBusy(busy) {
    sendButton.disabled = busy;
    questionElement.disabled = busy;
    if (!busy) questionElement.focus();
  }

  function addMessage(role, text) {
    var element = document.createElement('div');
    element.className = 'message message--' + role;
    element.textContent = text;
    messagesElement.appendChild(element);
    messagesElement.scrollTop = messagesElement.scrollHeight;
    return element;
  }

  function formatHistory() {
    return history
      .slice(-MAX_HISTORY_TURNS)
      .map(function (entry) {
        return 'Customer: ' + entry.question + '\nAssistant: ' + entry.answer;
      })
      .join('\n\n');
  }

  function finishTurn(answer, failure) {
    if (!turn) return;
    var finished = turn;
    turn = null;
    if (finished.subscription) {
      EpicStaff.call('sessions.unsubscribe', { subscription: finished.subscription }).catch(function () {});
    }
    if (failure) {
      finished.pendingElement.className = 'message message--error';
      finished.pendingElement.textContent = failure;
    } else {
      finished.pendingElement.className = 'message message--bot';
      finished.pendingElement.textContent = answer;
      history.push({ question: finished.question, answer: answer });
    }
    setBusy(false);
  }

  function send() {
    var question = questionElement.value.trim();
    if (!question || turn) return;
    if (question.length > MAX_QUESTION_LENGTH) {
      setStatus('Please keep the question under ' + MAX_QUESTION_LENGTH + ' characters.');
      return;
    }
    setStatus('');
    questionElement.value = '';
    addMessage('user', question);
    turn = { question: question, subscription: null, pendingElement: addMessage('pending', 'Thinking…') };
    setBusy(true);

    var current = turn;
    EpicStaff.call('flows.run', { flow: 'chat', variables: { question: question, history: formatHistory() } })
      .then(function (result) {
        return EpicStaff.call('sessions.subscribe', { session_id: result.session_id });
      })
      .then(function (result) {
        if (turn === current) current.subscription = result.subscription;
        else EpicStaff.call('sessions.unsubscribe', { subscription: result.subscription }).catch(function () {});
      })
      .catch(function (error) {
        if (turn === current) finishTurn(null, 'Could not ask the assistant: ' + error.message);
      });
  }

  EpicStaff.on('session.message', function (data, subscription) {
    if (!turn || subscription !== turn.subscription || data.message_type !== 'graph_end') return;
    var result = data.message_data && data.message_data.end_node_result;
    var answer = result && typeof result.answer === 'string' ? result.answer.trim() : '';
    finishTurn(answer || 'The assistant did not return an answer.', null);
  });

  EpicStaff.on('session.status', function (data, subscription) {
    if (!turn || subscription !== turn.subscription) return;
    if (FAILED_STATUSES[data.status]) finishTurn(null, 'The assistant stopped before answering (' + data.status + ').');
  });

  // The host closes a subscription a moment after the session ends, once late messages
  // (such as the answer) had time to arrive. Still no answer by then means there is none.
  EpicStaff.on('subscription.closed', function (data, subscription) {
    if (!turn || subscription !== turn.subscription) return;
    if (data.reason === 'error') finishTurn(null, 'Lost the connection to the assistant. Please ask again.');
    else finishTurn('The assistant finished without an answer.', null);
  });

  sendButton.addEventListener('click', send);
  questionElement.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });

  setBusy(true);
  setStatus('Connecting…');
  EpicStaff.ready.then(
    function (context) {
      document.title = context.plugin.name;
      setStatus('');
      setBusy(false);
    },
    function (error) {
      setStatus('This page could not connect to EpicStaff: ' + error.message);
    }
  );
})();
