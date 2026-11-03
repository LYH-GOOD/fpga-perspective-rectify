# Light27 AXIS/AXI-Lite contract

The original remap, camera, H coefficient format, 512x384 RGB565 line cache,
clock frequency and sharp/bypass datapath are retained. The added stage operates
on the **external RGB888 in a 32-bit carrier**, not on internal RGB565 words.

`axis_light_0` base 0x40002000, 4KiB address window, 32-bit AXI4-Lite with
independent AW/W handshakes and WSTRB. CLK and active-low synchronous reset are
the same nets as remap (FCLK0 approx83.333MHz). No clock domain crossing.

| Offset | Access | Meaning |
|---|---|---|
| 0x00 | RW | configured Q8 strength,0..256; values257..511 clamp256 |
| 0x04 | RO | version0x4c540001 |
| 0x08 | RO | parameter latched at first accepted pixel of current/last packet |
| 0x0c | RO | bit0 input packet open; bit1 any pixel pipeline valid |
| 0x10 | RO | completed output packet count, wraps uint32 |

Bits above8 are reserved/ignored. Unmapped reads return0, unmapped writes have
no effect. AXI responses OKAY. Read/response data remain stable under stalls.

AXIS uses32data/TLAST/valid/ready, no TKEEP/TUSER; all carrier bytes preserved
apart from RGB24. TLAST is the DMA **packet** end, not a video line marker.
Byte23:16 R,15:8 G,7:0 B;31:24 unchanged. No image size dependence.

Brightness estimate `Y=floor((R+2G+B)/4)`. Base compensation has knots
(16,0),(48,32),(112,32),(240,0), zero outside16..240; falling slope uses integer
floor division by4. Rounded compensation `floor((base*strength+128)/256)` is
limited by255-max(R,G,B), then added to all channels. Maximum lift32 levels;
black/white unchanged. Strength0 is bit-identical, including upper byte.
This changes global dark/mid brightness, not spatial illumination equalization.

Three elastic valid/ready pipeline stages; no full/line RAM or histogram.
Unstalled initiation interval1; output held unchanged during backpressure.
Reset drops in-flight pixels/packet state, clearsstrength and counters.
First accepted pixel locks parameter for its packet, including that pixel.
Configuration write committed on that same edge is used by a **later** packet.

The existing P1 owner writes configuration only before starting an entire
rectified frame, then keeps it across all DMA tiles of that frame. UI never
touches MMIO. Preview parameters coalesce at>=100ms frame boundaries; stable
frames do no light MMIO/clock sampling. On changes, driver checks configured
readback before submission and active value after all tiles complete. Display
actual values update only after successful HDMI submission of those pixels.

Zero BRAM and at most1DSP are synthesis acceptance targets. II1 has passed an
XSim test, not a board-FPS certification. Entire implementation timing/IO/DRC
and full source/pair checks precede release. Previous26 remains available.
