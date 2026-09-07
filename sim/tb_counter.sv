module tb_counter;

  localparam int WIDTH = 8;

  logic             clk = 0;
  logic             rst_n;
  logic             en;
  logic [WIDTH-1:0] count;

  counter #(.WIDTH(WIDTH)) dut (
      .clk  (clk),
      .rst_n(rst_n),
      .en   (en),
      .count(count)
  );

  always #5 clk = ~clk;

  initial begin
    $dumpfile("tb_counter.vcd");
    $dumpvars(0, tb_counter);

    rst_n = 0;
    en    = 0;
    #12;
    rst_n = 1;
    en    = 1;

    repeat (20) @(posedge clk);

    if (count !== 8'd19) $error("count mismatch: expected 19, got %0d", count);
    else $display("PASS: count = %0d", count);

    $finish;
  end

endmodule
