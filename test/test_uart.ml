open Hardcaml

type driver =
  { set : string -> int -> unit
  ; get : string -> int
  ; cycle : unit -> unit
  }

let make clocks_per_bit =
  let sim =
    Cyclesim.create (Protocol_emulator.Uart_tx.circuit ~clocks_per_bit ())
  in
  let set name value =
    let port = Cyclesim.in_port sim name in
    port := Bits.of_unsigned_int ~width:(Bits.width !port) value
  in
  let get name = Bits.to_unsigned_int !(Cyclesim.out_port sim name) in
  { set; get; cycle = (fun () -> Cyclesim.cycle sim) }
;;

let check d name expected context =
  let actual = d.get name in
  if actual <> expected
  then failwith (Printf.sprintf "%s: %s expected %d, got %d"
                   context name expected actual)
;;

let reset d =
  d.set "data" 0xA5;
  d.set "valid" 1;
  d.set "clear" 1;
  d.cycle ();
  check d "tx" 1 "synchronous reset";
  check d "ready" 0 "reset must suppress acceptance";
  d.set "valid" 0;
  d.set "clear" 0;
  d.cycle ();
  check d "tx" 1 "idle after reset";
  check d "ready" 1 "ready after reset"
;;

(* Independent pin-level oracle: no access to implementation registers. *)
let expected_bit byte bit =
  if bit = 0 then 0
  else if bit = 9 then 1
  else (byte lsr (bit - 1)) land 1
;;

let check_frame d ~clocks_per_bit ~byte ~disturb =
  (* Caller has just clocked the accepting edge. *)
  for offset = 0 to (10 * clocks_per_bit) - 1 do
    let context =
      Printf.sprintf "divider=%d byte=0x%02X frame-clock=%d"
        clocks_per_bit byte offset
    in
    check d "tx" (expected_bit byte (offset / clocks_per_bit)) context;
    check d "ready" 0 context;
    if disturb then d.set "data" ((byte lxor 0xFF lxor offset) land 0xFF);
    d.cycle ()
  done;
  check d "tx" 1 "end of full stop bit";
  check d "ready" 1 "frame must end after exactly 10*N clocks"
;;

let test_all_bytes clocks_per_bit =
  let d = make clocks_per_bit in
  reset d;
  for byte = 0 to 255 do
    d.set "data" byte;
    d.set "valid" 1;
    d.cycle ();
    (* Keep valid high and change data throughout the busy interval. *)
    check_frame d ~clocks_per_bit ~byte ~disturb:true;
    d.set "valid" 0;
    for _ = 1 to 3 do
      d.cycle ();
      check d "tx" 1 "idle after busy requests";
      check d "ready" 1 "busy requests must not be queued"
    done
  done
;;

let test_continuous_valid clocks_per_bit =
  let d = make clocks_per_bit in
  reset d;
  d.set "valid" 1;
  List.iter
    (fun byte ->
      check d "ready" 1 "between continuous frames";
      d.set "data" byte;
      d.cycle ();
      check_frame d ~clocks_per_bit ~byte ~disturb:false)
    [ 0x55; 0xAA; 0x00; 0xFF; 0x81 ];
  d.set "valid" 0;
  d.cycle ();
  check d "ready" 1 "continuous stream stopped"
;;

let test_reset_during_frame clocks_per_bit =
  let d = make clocks_per_bit in
  for offset = 0 to (10 * clocks_per_bit) - 1 do
    reset d;
    d.set "data" 0;
    d.set "valid" 1;
    d.cycle ();
    for _ = 1 to offset do d.cycle () done;
    reset d;
    d.set "data" 0xA5;
    d.set "valid" 1;
    d.cycle ();
    d.set "valid" 0;
    check_frame d ~clocks_per_bit ~byte:0xA5 ~disturb:false
  done
;;

let test_hello () =
  let clocks_per_bit = 3 in
  let sim =
    Cyclesim.create (Protocol_emulator.Uart_tx.hello_circuit ~clocks_per_bit ())
  in
  let clear = Cyclesim.in_port sim "clear" in
  let tx = Cyclesim.out_port sim "tx" in
  clear := Bits.vdd;
  Cyclesim.cycle sim;
  if Bits.to_unsigned_int !tx <> 1 then failwith "hello reset";
  clear := Bits.gnd;
  for offset = 0 to (4 * ((10 * clocks_per_bit) + 1)) - 1 do
    Cyclesim.cycle sim;
    let frame_offset = offset mod ((10 * clocks_per_bit) + 1) in
    let expected =
      if frame_offset = 10 * clocks_per_bit then 1
      else expected_bit 0x55 (frame_offset / clocks_per_bit)
    in
    if Bits.to_unsigned_int !tx <> expected then failwith "hello frame timing"
  done
;;

(* VCD from the real Cyclesim pin values, at a 10 MHz simulation clock.
   Request with: dune exec test/test_uart.exe -- uart.vcd *)
let write_vcd filename =
  let clocks_per_bit = 87 in
  let d = make clocks_per_bit in
  let oc = open_out filename in
  Fun.protect ~finally:(fun () -> close_out oc) (fun () ->
    output_string oc
      "$timescale 1ns $end\n$scope module uart $end\n\
       $var wire 1 ! clock $end\n$var wire 1 \" tx $end\n\
       $var wire 1 # ready $end\n$var wire 1 $ clear $end\n\
       $var wire 1 % valid $end\n$var wire 8 & data $end\n\
       $upscope $end\n$enddefinitions $end\n";
    let binary8 n = String.init 8 (fun i -> if n land (1 lsl (7-i)) = 0 then '0' else '1') in
    for cycle = 0 to 1799 do
      let clear = if cycle < 2 then 1 else 0 in
      let valid = if cycle = 4 || cycle = 900 then 1 else 0 in
      let data = if cycle < 900 then 0x55 else 0xA5 in
      d.set "clear" clear;
      d.set "valid" valid;
      d.set "data" data;
      Printf.fprintf oc "#%d\n0!\n%d$\n%d%%\nb%s &\n"
        (cycle * 100) clear valid (binary8 data);
      d.cycle ();
      Printf.fprintf oc "#%d\n1!\n%d\"\n%d#\n"
        ((cycle * 100) + 50) (d.get "tx") (d.get "ready")
    done);
  Printf.printf "Wrote %s (10 MHz clock, 87 clocks/bit, bytes 0x55 and 0xA5).\n" filename
;;

let () =
  List.iter test_all_bytes [ 1; 2; 3; 7; 16; 87 ];
  List.iter test_continuous_valid [ 1; 3; 87 ];
  List.iter test_reset_during_frame [ 1; 3; 7 ];
  test_hello ();
  let rejects_zero =
    try
      ignore (Protocol_emulator.Uart_tx.circuit ~clocks_per_bit:0 ());
      false
    with Invalid_argument _ -> true
  in
  if not rejects_zero then failwith "zero divider must be rejected";
  print_endline "PASS: all 256 bytes at 6 dividers; busy input changes; continuous valid; reset at every frame phase; hello demo; invalid divider.";
  match Array.to_list Sys.argv with
  | [ _ ] -> ()
  | [ _; filename ] -> write_vcd filename
  | _ -> failwith "Usage: test_uart.exe [waveform.vcd]"
;;
