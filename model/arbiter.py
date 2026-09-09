"""iSLIP matching: request/grant/accept over a VOQ occupancy bitmap.

Mirrors the `rr_pointer` primitive planned for the RTL (Milestone 1) so the
same rotate-on-match-only pointer logic is exercised in both the model and
hardware. Pointer update rule (the classic easy-to-get-wrong detail): a
pointer only advances for inputs/outputs matched in *iteration 1* of a given
slot, regardless of which iteration ultimately resolves the remaining
requests -- this is what preserves iSLIP's desynchronization/fairness
property. See McKeown, "The iSLIP Scheduling Algorithm for Input-Queued
Switches," 1999.
"""

from __future__ import annotations


class RoundRobinPointer:
    """A single rotating priority pointer over `n` candidates."""

    def __init__(self, n: int):
        self.n = n
        self.value = 0

    def priority_order(self) -> list[int]:
        """Candidates in priority order starting at the current pointer."""
        return [(self.value + i) % self.n for i in range(self.n)]

    def advance_past(self, winner: int) -> None:
        self.value = (winner + 1) % self.n


class ISlipArbiter:
    def __init__(self, n_ports: int, iterations: int):
        self.n = n_ports
        self.iterations = iterations
        self.grant_ptr = [RoundRobinPointer(n_ports) for _ in range(n_ports)]  # per output
        self.accept_ptr = [RoundRobinPointer(n_ports) for _ in range(n_ports)]  # per input

    def match(self, requests: list[set[int]]) -> list[tuple[int, int]]:
        """requests[i] = set of outputs input i has a nonempty VOQ for.
        Returns list of (input, output) matched pairs for this slot."""
        n = self.n
        unmatched_inputs = set(range(n))
        unmatched_outputs = set(range(n))
        matches: list[tuple[int, int]] = []
        iter1_matched_inputs: set[int] = set()
        iter1_matched_outputs: set[int] = set()

        remaining_requests = [set(r) for r in requests]

        for it in range(self.iterations):
            if not unmatched_inputs or not unmatched_outputs:
                break

            # --- Phase 1: Request (implicit -- remaining_requests already
            # reflects only unmatched inputs' still-pending destinations) ---
            active_requests = {
                i: {o for o in remaining_requests[i] if o in unmatched_outputs}
                for i in unmatched_inputs
                if remaining_requests[i] & unmatched_outputs
            }

            # --- Phase 2: Grant -- each unmatched output picks among its
            # requesters by round-robin priority ---
            grants: dict[int, int] = {}  # output -> chosen input
            for o in list(unmatched_outputs):
                requesters = [i for i, outs in active_requests.items() if o in outs]
                if not requesters:
                    continue
                for candidate in self.grant_ptr[o].priority_order():
                    if candidate in requesters:
                        grants[o] = candidate
                        break

            # --- Phase 3: Accept -- each granted input picks among the
            # outputs that granted it, by round-robin priority ---
            grants_by_input: dict[int, list[int]] = {}
            for o, i in grants.items():
                grants_by_input.setdefault(i, []).append(o)

            accepted_this_iter: list[tuple[int, int]] = []
            for i, offered_outputs in grants_by_input.items():
                for candidate in self.accept_ptr[i].priority_order():
                    if candidate in offered_outputs:
                        accepted_this_iter.append((i, candidate))
                        break

            for i, o in accepted_this_iter:
                matches.append((i, o))
                unmatched_inputs.discard(i)
                unmatched_outputs.discard(o)
                if it == 0:
                    iter1_matched_inputs.add(i)
                    iter1_matched_outputs.add(o)

        # Pointer update: only for iteration-1 matches (desynchronization rule).
        for i, o in matches:
            if i in iter1_matched_inputs and o in iter1_matched_outputs:
                self.grant_ptr[o].advance_past(i)
                self.accept_ptr[i].advance_past(o)

        return matches
