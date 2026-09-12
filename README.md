# Clos_SV

A high-radix, arbitrated Ethernet crossbar fabric, built as a from-scratch interview-prep
project targeting switch-silicon/high-radix networking roles. Covers the full stack: topology
selection reasoned from real constraints (size, clock frequency, blocking), SystemVerilog RTL,
a Python performance model, and the open-source EDA toolchain to check whether it'll actually
hit timing.

See **[docs/arch-spec.md](docs/arch-spec.md)** for the full architecture writeup — candidate
topology comparison (monolithic crossbar, butterfly, Beneš, Batcher-Banyan, Clos), why Clos was
selected, the multi-tier scaling math, and an interview talking-points checklist.

---

## Repository layout

```
Clos_SV/
├── docs/
│   ├── arch-spec.md       # architecture decision record + study guide
│   └── diagrams/          # SVG diagrams referenced from arch-spec.md
├── rtl/                   # SystemVerilog design sources
├── sim/                   # SystemVerilog testbenches
├── model/                 # Python VOQ + iSLIP performance model (golden reference)
│   └── README.md          # model-specific usage docs
├── Makefile                # sim / lint / format / wave targets
└── .vscode/settings.json   # Verible lint/format wired into the SystemVerilog extension
```

## Status / roadmap

- [x] **Milestone 1 scaffold** — toolchain, project structure, reference counter + testbench
      (`rtl/counter.sv`, `sim/tb_counter.sv`) proving the sim/lint flow end-to-end. The real
      VOQ + iSLIP RTL for Milestone 1 (8×8 reference design) has not been written yet.
- [ ] Milestone 1 — 8×8 VOQ + iSLIP RTL, validated against `model/` as a golden reference.
- [ ] Milestone 2 — scale to N=128 monolithic crossbar; characterize arbiter timing.
- [ ] Milestone 3 — 3-stage Clos (rearrangeable, N=128) with CRRD-style scheduling.

Full milestone spec: [docs/arch-spec.md §6](docs/arch-spec.md#6-resulting-design-parameters).

---

## Toolchain

| Tool | Purpose | Install |
|---|---|---|
| [Icarus Verilog](http://iverilog.icarus.com/) | Simulation | `brew install icarus-verilog` |
| [Verilator](https://www.veripool.org/verilator/) | Simulation / lint | `brew install verilator` |
| [GTKWave](https://gtkwave.sourceforge.net/) | Waveform viewer | `brew install --cask gtkwave` |
| [Verible](https://github.com/chipsalliance/verible) | Lint + format | prebuilt binary — no Homebrew formula, see below |
| [Yosys](https://yosyshq.net/yosys/) | Synthesis | `brew install yosys` |
| [OpenSTA](https://github.com/parallaxsw/OpenSTA) | Multi-corner static timing analysis | build from source — see below |
| [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) | Full RTL-to-GDSII place & route | Docker — see below |
| [ASAP7](https://github.com/The-OpenROAD-Project/asap7) | Predictive 7nm PDK (multi-corner Liberty + LEF) | `git clone`, see below |
| [cocotb](https://www.cocotb.org/) | Python-based RTL testbench framework (planned verification environment) | `pip install cocotb` — **installed, not yet wired up**; setup deferred until Milestone 1 RTL exists to test against. If `cocotb-config` isn't found after install on a pyenv-managed Python, run `pyenv rehash`. |

**Verible** (no Homebrew formula — install the prebuilt release binary):
```
curl -sL -o verible.tar.gz "https://github.com/chipsalliance/verible/releases/latest/download/verible-<version>-macOS.tar.gz"
tar -xzf verible.tar.gz && cp verible-*/bin/* /opt/homebrew/bin/
```

**OpenSTA** (build from source — see [OpenSTA's own Brewfile](https://github.com/parallaxsw/OpenSTA/blob/master/Brewfile) for exact deps; note it needs `tcl-tk@8`, not the current `tcl-tk` which is Tcl 9 and incompatible):
```
brew install cmake swig bison flex eigen tcl-tk@8
brew tap mht208/formal && brew install mht208/formal/cudd
git clone https://github.com/parallaxsw/OpenSTA.git
cd OpenSTA && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RELEASE \
  -DTCL_LIBRARY=$(brew --prefix tcl-tk@8)/lib/libtcl8.6.dylib \
  -DTCL_HEADER=$(brew --prefix tcl-tk@8)/include/tcl-tk/tcl.h
make -j$(sysctl -n hw.ncpu)
ln -sf $(pwd)/sta /opt/homebrew/bin/sta   # put it on PATH
```

**ASAP7 PDK** (BSD-3-Clause, no NDA — the closest open, deep-submicron-class stand-in; real
foundry nodes like TSMC N3/N2 require a foundry relationship and cannot be obtained otherwise):
```
git clone --depth 1 https://github.com/The-OpenROAD-Project/asap7.git
cd asap7
git submodule update --init --depth 1 asap7sc7p5t_28 asap7_pdk_r1p7
# Liberty timing files ship compressed:
brew install p7zip
cd asap7sc7p5t_28/LIB/NLDM && for f in *RVT*.lib.7z; do 7z x -y "$f"; done
```
This gives multi-corner Liberty (`TT`/`SS`/`FF`, i.e. typical/slow/fast) and LEF files — enough
for OpenSTA to check whether the design meets a target frequency across PVT corners.

**OpenROAD-flow-scripts** (Docker — the officially supported path; native macOS builds of
OpenROAD are fragile since Linux is the tested target):
```
brew install --cask docker   # then launch Docker.app once to finish setup
docker pull --platform linux/amd64 openroad/orfs:latest   # no native arm64 image published
git clone https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git
cd OpenROAD-flow-scripts/flow
util/docker_shell make DESIGN_CONFIG=./designs/asap7/gcd/config.mk   # smoke test
```
ORFS bundles its own complete ASAP7 platform files (LEF/lib/GDS/KLayout/RC rules) — the
separately cloned ASAP7 PDK above is still useful as the authoritative full multi-Vt library.

---

## Quick start

```
# Simulate + view waveform
make sim
make wave

# Lint / format
make lint
make fmt

# Clean build artifacts
make clean
```

```
# Run the Python performance model
cd model
python3 sim.py --n-ports 128 --load 0.9 --pattern hotspot --hotspot-frac 0.7 \
    --length-dist bimodal --cell-size 64 --iterations 3 --slots 20000 --seed 1
```

---

## Working in VS Code

**Open the project**: `code .` from this directory, or File → Open Folder.

**Extensions already set up** (see `.vscode/settings.json`):
- `mshr-h.veriloghdl` — SystemVerilog syntax, wired to Verible for lint/format and language
  server. Format-on-save is enabled for `.sv`/`.svh` files.
- `bierner.markdown-mermaid` — renders the Mermaid diagrams in `docs/arch-spec.md` in Markdown
  preview (`Cmd+Shift+V`).
- `ms-python.python` + Pylance + debugpy — for editing/running/debugging `model/`.

**Running things from the integrated terminal** (`` Ctrl+` ``): all the `make`/`python3`
commands above work identically inside VS Code's terminal — nothing VS Code-specific needed.

**Running the Python model without a terminal**: open any file in `model/`, use the ▷ "Run
Python File" button in the top-right of the editor, or set breakpoints and use the Debug panel
(the Python extension picks up `sim.py`'s argparse CLI — set args via a `launch.json` if you
want to debug with specific flags instead of the defaults).

**Previewing the architecture doc with diagrams**: open `docs/arch-spec.md`, then
`Cmd+Shift+V` (or the preview icon in the tab bar) to render it with Mermaid diagrams and the
SVG topology drawings inline.

## Git from VS Code

This repo is already connected to `https://github.com/Jamon111/Clos_SV` and authenticated via
the GitHub CLI (`gh auth status` shows a logged-in token) — VS Code's Source Control panel
shells out to the same system `git`, so commit/push/pull work the same way they do from a
terminal, no extra setup needed.

- **Source Control panel**: the branch icon in the left sidebar (or `Cmd+Shift+G`). Shows
  changed files, staged/unstaged diffs.
- **Commit**: stage files (`+` next to each file, or `+` next to "Changes" to stage all), type
  a message in the box at the top, `Cmd+Enter` to commit.
- **Push/Pull**: the sync icon in the bottom-left status bar (shows ↑/↓ counts of commits ahead/
  behind `origin/main`), or `...` menu in the Source Control panel → Push / Pull. `Cmd+Shift+P`
  → "Git: Push" / "Git: Pull" also work from the command palette.
- **If a credential prompt appears**: VS Code will open a browser-based GitHub sign-in flow
  automatically the first time; after that it's cached the same way the terminal's `gh` auth
  is. No password entry should ever be needed.

## Note on the ASAP7/OpenSTA/OpenROAD setup above

None of that lives in this repo — it's third-party tooling and a large PDK, kept outside the
project (`~/eda/tools`, `~/eda/pdks`) rather than committed, so the repo itself stays small and
focused on the actual design. Anyone cloning this repo needs to set those up separately using
the commands above; only the SystemVerilog, docs, and Python model are this project's own IP.
