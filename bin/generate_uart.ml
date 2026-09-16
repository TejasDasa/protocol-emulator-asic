open Hardcaml

let usage () =
  prerr_endline "Usage: generate_uart.exe [tx|hello [clock_hz baud]]";
  exit 2
;;

let () =
  let mode, clock_hz, baud =
    match Array.to_list Sys.argv with
    | [ _ ] -> "tx", 10_000_000, 115_200
    | [ _; mode ] -> mode, 10_000_000, 115_200
    | [ _; mode; clock; baud ] ->
      (try mode, int_of_string clock, int_of_string baud with Failure _ -> usage ())
    | _ -> usage ()
  in
  if clock_hz < 1 || clock_hz > 1_000_000_000 || baud < 1 || baud > clock_hz
  then usage ();
  let clocks_per_bit = (clock_hz + (baud / 2)) / baud in
  let circuit =
    match mode with
    | "tx" -> Protocol_emulator.Uart_tx.circuit ~clocks_per_bit ()
    | "hello" -> Protocol_emulator.Uart_tx.hello_circuit ~clocks_per_bit ()
    | _ -> usage ()
  in
  let actual_baud = float_of_int clock_hz /. float_of_int clocks_per_bit in
  Printf.eprintf "clocks_per_bit=%d; actual baud=%.3f; error=%+.3f%%\n%!"
    clocks_per_bit actual_baud
    ((actual_baud /. float_of_int baud -. 1.) *. 100.);
  Rtl.print Verilog circuit
;;
