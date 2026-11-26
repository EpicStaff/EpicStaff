import signal

from es_plugins.launcher import kill_by_uid


class EmptyProcessTable:
    def living_pids_of_uid(self, uid):
        return []


def test_a_kill_round_is_sent_even_when_the_table_reports_no_living_process(monkeypatch):
    sent = []
    monkeypatch.setattr(kill_by_uid, "signal_uid", lambda uid, number: sent.append((uid, number)))

    outcome = kill_by_uid.kill_uid(20001, EmptyProcessTable())

    assert sent == [(20001, signal.SIGKILL)]
    assert outcome.rounds == 1
    assert outcome.remaining == ()


class TableThatLosesItsProcessAfterOneRead:
    def __init__(self):
        self._answers = [[77], []]

    def living_pids_of_uid(self, uid):
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def test_another_round_is_sent_while_the_table_still_reports_a_living_process(monkeypatch):
    sent = []
    monkeypatch.setattr(kill_by_uid, "signal_uid", lambda uid, number: sent.append((uid, number)))

    outcome = kill_by_uid.kill_uid(20001, TableThatLosesItsProcessAfterOneRead())

    assert sent == [(20001, signal.SIGKILL)] * 2
    assert outcome.rounds == 2
    assert outcome.remaining == ()
