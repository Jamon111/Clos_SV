SRC   := rtl/counter.sv
TB    := sim/tb_counter.sv
TOP   := tb_counter
VCD   := tb_counter.vcd

.PHONY: sim wave lint fmt clean

sim:
	iverilog -g2012 -o sim.out $(SRC) $(TB)
	vvp sim.out

wave: sim
	gtkwave $(VCD) &

lint:
	verible-verilog-lint $(SRC) $(TB)

fmt:
	verible-verilog-format --inplace $(SRC) $(TB)

clean:
	rm -f sim.out $(VCD)
