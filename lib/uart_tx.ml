open Hardcaml

(* Minimum positive width capable of representing [n]. *)
let width_for n =
  let rec loop n width =
    if n = 0 then max 1 width else loop (n lsr 1) (width + 1)
  in
  loop n 0
;;

(* All input signals belong to [clock]'s domain. [clear] is synchronous,
   active high. Accept a byte only when [valid && ready] before an edge.
   The accepted byte is latched; changing [data] while busy is harmless. *)
let create ~clocks_per_bit ~clock ~clear ~valid ~data =
  if clocks_per_bit < 1 then invalid_arg "clocks_per_bit must be >= 1";
  let timer_width = width_for (clocks_per_bit - 1) in
  let open Signal in
  let spec = Reg_spec.create ~clock ~clear () in
  let remaining = wire 4 in
  let timer = wire timer_width in
  let frame = wire 10 in
  (* Store the inverted TX level so the default clear-to-zero produces
     an idle-high pin. TX comes from one register through an inverter. *)
  let tx_low = wire 1 in
  let active = ~:(remaining ==: zero 4) in
  let ready = ~:active &: ~:clear in
  let accept = valid &: ready in
  let bit_end = active &: (timer ==: zero timer_width) in
  let reload = of_unsigned_int ~width:timer_width (clocks_per_bit - 1) in
  remaining
  <-- reg spec ~enable:vdd
        (mux2 accept (of_unsigned_int ~width:4 10)
           (mux2 bit_end (remaining -: of_unsigned_int ~width:4 1) remaining));
  timer
  <-- reg spec ~enable:vdd
        (mux2 accept reload
           (mux2 active
              (mux2 bit_end reload
                 (timer -: of_unsigned_int ~width:timer_width 1))
              (zero timer_width)));
  frame
  <-- reg spec ~enable:vdd
        (mux2 accept (concat_msb [ vdd; data; gnd ])
           (mux2 bit_end
              (concat_msb [ vdd; select frame ~high:9 ~low:1 ])
              frame));
  tx_low
  <-- reg spec ~enable:vdd
        (mux2 accept vdd
           (mux2 bit_end (~:(select frame ~high:1 ~low:1)) tx_low));
  ~:tx_low, ready
;;

let circuit ~clocks_per_bit () =
  let open Signal in
  let tx, ready =
    create ~clocks_per_bit
      ~clock:(input "clock" 1) ~clear:(input "clear" 1)
      ~valid:(input "valid" 1) ~data:(input "data" 8)
  in
  Circuit.create_exn ~name:"uart_tx" [ output "tx" tx; output "ready" ready ]
;;

(* Autonomous first-pin demonstration: repeated ASCII 'U', with one
   additional idle clock between complete 8N1 frames. *)
let hello_circuit ~clocks_per_bit () =
  let open Signal in
  let tx, _ready =
    create ~clocks_per_bit
      ~clock:(input "clock" 1) ~clear:(input "clear" 1)
      ~valid:vdd ~data:(of_unsigned_int ~width:8 0x55)
  in
  Circuit.create_exn ~name:"uart_hello" [ output "tx" tx ]
;;
