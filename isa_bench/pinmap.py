"""Build the SPEC §11.1/§11.2 pin-assignment chain, and refuse to build one
that cannot work.

The chain is just bits, and every way of getting it wrong produces a design
that configures cleanly, runs, and quietly does nothing useful:

  * a program that uses `load`, `push` or the `fifo` test with no pin selecting
    the host port never receives a byte and never delivers one. `fifo` is
    permanently false, so a transmitter sits in its idle row forever; `push`
    fills a 4-deep RX FIFO and then drops bytes, setting only a sticky flag
    nobody can read. Nothing reports it.
  * an open-drain slot on a `uo_out` pin can never release the net (§11.1), so
    an I2C master drives SDA low and holds the bus.

Both are the class of silent failure the FIFO sticky flags exist to catch, and
both are decidable from the program and the assignment together. So they are
rejected here, at construction, rather than discovered on silicon.
"""


def _bits_for(n):
    return max(1, (n - 1).bit_length())


class PinPlan:
    """A pin assignment for NSM machines, checked against their programs."""

    def __init__(self, nsm=5, nslot=3, nin=2, nout=16, npin=16, n_uo=8):
        self.nsm, self.nslot, self.nin = nsm, nslot, nin
        self.nout, self.npin, self.n_uo = nout, npin, n_uo
        self.oselw = _bits_for(nsm * nslot)
        self.iselw = _bits_for(npin)
        self.host_code = (1 << self.oselw) - 1
        if nsm * nslot > self.host_code:
            raise ValueError(
                f"{nsm * nslot} drivers fill the {self.oselw}-bit output select "
                f"field, leaving no free code for the host port (§11.2)")
        self.out = {}          # pin -> driver index
        self.inp = {}          # (machine, input) -> pin
        self.host = None       # (dout_pin, stb_pin, din_pin)
        self._od = set()       # driver indices that are open drain

    # ---- building -------------------------------------------------------
    def drive(self, machine, slot, pin, od=False):
        drv = machine * self.nslot + slot
        if pin in self.out:
            raise ValueError(
                f"pin {pin} already selects driver {self.out[pin]}; a pin "
                f"chooses one driver (§11.1)")
        if od and pin < self.n_uo:
            raise ValueError(
                f"machine {machine} slot {slot} is open drain and cannot go on "
                f"uo_out pin {pin}: uo_out is always driven and can never "
                f"release the net (§11.1). Use a uio pin, {self.n_uo}..{self.nout - 1}.")
        self.out[pin] = drv
        if od:
            self._od.add(drv)
        return self

    def read(self, machine, index, pin):
        self.inp[(machine, index)] = pin
        return self

    def host_port(self, dout_pin, stb_pin, din_pin):
        if dout_pin in self.out:
            raise ValueError(
                f"pin {dout_pin} already selects driver {self.out[dout_pin]}; "
                f"the host port output needs a pin of its own (§11.2)")
        self.host = (dout_pin, stb_pin, din_pin)
        return self

    # ---- the check ------------------------------------------------------
    @staticmethod
    def _host_users(prog):
        """Which host-dependent row fields a program actually uses."""
        used = set()
        for r in prog.rows:
            for a in r.act:
                if a in ("load", "push"):
                    used.add(a)
            if r.test == "fifo":
                used.add("fifo")
        return used

    def validate(self, programs):
        """`programs[m]` is machine m's SttProgram, or None if unused."""
        need = {}
        for m, prog in enumerate(programs):
            if prog is None:
                continue
            u = self._host_users(prog)
            if u:
                need[m] = sorted(u)
        if need and self.host is None:
            who = "; ".join(
                f"machine {m} uses {', '.join(v)}" for m, v in sorted(need.items()))
            raise ValueError(
                f"no pin selects the host port, but {who}. Those rows move "
                f"bytes between a machine and the host, and with no host port "
                f"the `fifo` test is permanently false and `push` fills the RX "
                f"FIFO and then drops bytes with only a sticky flag to show "
                f"for it. Assign one with host_port(), or remove the rows "
                f"(SPEC §11.2).")
        return self

    # ---- emission -------------------------------------------------------
    def chain(self, programs=None):
        """(value, nbits) for the pin-assignment chain, run at bit 0 and sent
        first. Validates first when given the programs."""
        if programs is not None:
            self.validate(programs)
        obits = self.nout * self.oselw
        ibits = self.nsm * self.nin * self.iselw
        o_hen = 1 + obits + ibits
        v = 1                                     # bit 0 = run
        for pin, drv in self.out.items():
            v |= drv << (1 + pin * self.oselw)
        for (m, i), pin in self.inp.items():
            v |= pin << (1 + obits + (m * self.nin + i) * self.iselw)
        if self.host is not None:
            dout, stb, din = self.host
            v |= self.host_code << (1 + dout * self.oselw)
            v |= 1 << o_hen
            v |= stb << (o_hen + 1)
            v |= din << (o_hen + 1 + self.iselw)
        return v, o_hen + 1 + 2 * self.iselw
