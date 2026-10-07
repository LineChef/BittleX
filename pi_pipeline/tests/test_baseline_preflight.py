"""baseline_runs.preflight: a silent BiBoard stops the batch with a spoken message instead of 'finishing' runs that never moved G2."""
from pi_pipeline.gait import baseline_runs as B


class Link:
    def __init__(self, reply):
        self.reply, self.closed = reply, False

    def drain(self, s):
        pass

    def send(self, cmd):
        return self.reply

    def close(self):
        self.closed = True


def test_answering_board_returns_the_voltage_and_closes_the_link():
    lk = Link("Voltage: 8.31 V")
    said = []
    assert B.preflight(lambda: lk, said.append, sleep=lambda s: None) == 8.31 and lk.closed and not said


def test_silent_board_says_so_and_returns_none():
    said, tries = [], []
    def open_link():
        tries.append(1)
        return Link(None)
    assert B.preflight(open_link, said.append, attempts=3, sleep=lambda s: None) is None
    assert len(tries) == 3 and "not answering" in said[0]


def test_unopenable_port_counts_as_silent():
    said = []
    assert B.preflight(lambda: None, said.append, attempts=2, sleep=lambda s: None) is None and said
