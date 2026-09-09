"""Cell representation for the VOQ + iSLIP performance model.

A cell carries only the metadata egress needs to reassemble packets and the
scoreboard needs to verify correctness -- it is not a bit-accurate model of
an RTL flit. Physical datapath width belongs in the RTL/testbench, not here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    cell_id: int      # globally unique, monotonically increasing
    src: int          # ingress port
    dst: int          # egress port
    packet_id: int    # unique per packet, monotonic per (src, dst) flow
    seq: int          # 0-indexed position within its packet
    is_last: bool     # last cell of its packet
    gen_time: int     # slot time the *packet* was generated (all its cells share this)
                      # model-only field, for latency measurement convenience in this
                      # non-synthesizable model. Do NOT carry an equivalent timestamp
                      # into the RTL flit -- wastes real bits in silicon. In RTL, the
                      # testbench measures latency externally, keyed by a sequence/tag
                      # field that IS part of the flit (e.g. packet_id/seq above).
