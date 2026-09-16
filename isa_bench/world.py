"""Shared cycle-based simulation world used by every ISA.

Each cycle:
  1. devices (the far side of the protocol, plus the host script) update
  2. nets resolve
  3. the core under test steps, reading inputs through a synchronizer
  4. nets resolve again and are recorded
"""
from collections import deque


class Net:
    def __init__(self, name, pull=None):
        self.name = name
        self.pull = pull            # 1 = pull-up, 0 = pull-down, None = none
        self.drivers = {}
        self.value = pull if pull is not None else 0

    def drive(self, who, v):
        """v = 0, 1, or None (released)."""
        if v is None:
            self.drivers.pop(who, None)
        else:
            self.drivers[who] = int(v)

    def resolve(self, world):
        vals = set(self.drivers.values())
        if 0 in vals and 1 in vals:
            world.error(f"contention on {self.name}: {self.drivers}")
            self.value = 0
        elif 0 in vals:
            self.value = 0
        elif 1 in vals:
            self.value = 1
        elif self.pull is not None:
            self.value = self.pull
        # else: floating, keep last value


class World:
    def __init__(self, nets, sync=2):
        self.nets = {name: Net(name, pull) for name, pull in nets}
        self.history = {name: [] for name in self.nets}
        self.sync = sync
        self.t = 0
        self.tx_fifo = deque()      # host -> core
        self.rx_fifo = []           # core -> host
        self.devices = []
        self.errors = []

    def error(self, msg):
        if len(self.errors) < 20:
            self.errors.append(f"t={self.t}: {msg}")

    def value(self, name):
        return self.nets[name].value

    def read_sync(self, name):
        """What the core sees: the net value `sync` cycles ago."""
        h = self.history[name]
        i = len(h) - self.sync
        if i < 0:
            return h[0] if h else self.nets[name].value
        return h[i]

    def resolve(self):
        for n in self.nets.values():
            n.resolve(self)

    def run(self, core, max_cycles, done):
        self.resolve()
        for t in range(max_cycles):
            self.t = t
            for d in self.devices:
                d.step(self)
            self.resolve()
            core.step(self)
            self.resolve()
            for name, n in self.nets.items():
                self.history[name].append(n.value)
            if done(self):
                return True
        self.error("timeout")
        return False


class Host:
    """Scripted host: a list of (condition, action) pairs, each fired once, in order."""

    def __init__(self, script):
        self.script = list(script)

    def step(self, w):
        while self.script and self.script[0][0](w):
            _, action = self.script.pop(0)
            action(w)

    @property
    def finished(self):
        return not self.script
