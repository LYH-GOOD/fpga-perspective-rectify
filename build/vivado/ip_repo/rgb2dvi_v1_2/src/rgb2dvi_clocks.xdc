# Light27 project uses kGenerateSerialClk=false.
# SerialClk and PixelClk are siblings of axi_dynclk MMCM.
# Parent MMCM/BUFIO/BUFR auto-derived clocks constrain both nets.
# Do not invent a non-existent PixelClk -> SerialClk generated-clock path.
