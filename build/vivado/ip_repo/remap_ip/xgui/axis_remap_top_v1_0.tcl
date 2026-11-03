# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  set Page_0 [ipgui::add_page $IPINST -name "Page 0"]
  ipgui::add_param $IPINST -name "ACC_W" -parent ${Page_0}
  ipgui::add_param $IPINST -name "ADDR_AW" -parent ${Page_0}
  ipgui::add_param $IPINST -name "DW" -parent ${Page_0}
  ipgui::add_param $IPINST -name "FRAC_BITS" -parent ${Page_0}
  ipgui::add_param $IPINST -name "MAX_W" -parent ${Page_0}
  ipgui::add_param $IPINST -name "NCH" -parent ${Page_0}
  ipgui::add_param $IPINST -name "NORM_SCALE" -parent ${Page_0}
  ipgui::add_param $IPINST -name "PIX_W" -parent ${Page_0}
  ipgui::add_param $IPINST -name "ROWS" -parent ${Page_0}
  ipgui::add_param $IPINST -name "ROW_AW" -parent ${Page_0}


}

proc update_PARAM_VALUE.ACC_W { PARAM_VALUE.ACC_W } {
	# Procedure called to update ACC_W when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.ACC_W { PARAM_VALUE.ACC_W } {
	# Procedure called to validate ACC_W
	return true
}

proc update_PARAM_VALUE.ADDR_AW { PARAM_VALUE.ADDR_AW } {
	# Procedure called to update ADDR_AW when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.ADDR_AW { PARAM_VALUE.ADDR_AW } {
	# Procedure called to validate ADDR_AW
	return true
}

proc update_PARAM_VALUE.DW { PARAM_VALUE.DW } {
	# Procedure called to update DW when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.DW { PARAM_VALUE.DW } {
	# Procedure called to validate DW
	return true
}

proc update_PARAM_VALUE.FRAC_BITS { PARAM_VALUE.FRAC_BITS } {
	# Procedure called to update FRAC_BITS when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.FRAC_BITS { PARAM_VALUE.FRAC_BITS } {
	# Procedure called to validate FRAC_BITS
	return true
}

proc update_PARAM_VALUE.MAX_W { PARAM_VALUE.MAX_W } {
	# Procedure called to update MAX_W when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.MAX_W { PARAM_VALUE.MAX_W } {
	# Procedure called to validate MAX_W
	return true
}

proc update_PARAM_VALUE.NCH { PARAM_VALUE.NCH } {
	# Procedure called to update NCH when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.NCH { PARAM_VALUE.NCH } {
	# Procedure called to validate NCH
	return true
}

proc update_PARAM_VALUE.NORM_SCALE { PARAM_VALUE.NORM_SCALE } {
	# Procedure called to update NORM_SCALE when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.NORM_SCALE { PARAM_VALUE.NORM_SCALE } {
	# Procedure called to validate NORM_SCALE
	return true
}

proc update_PARAM_VALUE.PIX_W { PARAM_VALUE.PIX_W } {
	# Procedure called to update PIX_W when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.PIX_W { PARAM_VALUE.PIX_W } {
	# Procedure called to validate PIX_W
	return true
}

proc update_PARAM_VALUE.ROWS { PARAM_VALUE.ROWS } {
	# Procedure called to update ROWS when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.ROWS { PARAM_VALUE.ROWS } {
	# Procedure called to validate ROWS
	return true
}

proc update_PARAM_VALUE.ROW_AW { PARAM_VALUE.ROW_AW } {
	# Procedure called to update ROW_AW when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.ROW_AW { PARAM_VALUE.ROW_AW } {
	# Procedure called to validate ROW_AW
	return true
}


proc update_MODELPARAM_VALUE.NCH { MODELPARAM_VALUE.NCH PARAM_VALUE.NCH } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.NCH}] ${MODELPARAM_VALUE.NCH}
}

proc update_MODELPARAM_VALUE.DW { MODELPARAM_VALUE.DW PARAM_VALUE.DW } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.DW}] ${MODELPARAM_VALUE.DW}
}

proc update_MODELPARAM_VALUE.PIX_W { MODELPARAM_VALUE.PIX_W PARAM_VALUE.PIX_W } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.PIX_W}] ${MODELPARAM_VALUE.PIX_W}
}

proc update_MODELPARAM_VALUE.ROW_AW { MODELPARAM_VALUE.ROW_AW PARAM_VALUE.ROW_AW } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.ROW_AW}] ${MODELPARAM_VALUE.ROW_AW}
}

proc update_MODELPARAM_VALUE.ROWS { MODELPARAM_VALUE.ROWS PARAM_VALUE.ROWS } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.ROWS}] ${MODELPARAM_VALUE.ROWS}
}

proc update_MODELPARAM_VALUE.FRAC_BITS { MODELPARAM_VALUE.FRAC_BITS PARAM_VALUE.FRAC_BITS } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.FRAC_BITS}] ${MODELPARAM_VALUE.FRAC_BITS}
}

proc update_MODELPARAM_VALUE.NORM_SCALE { MODELPARAM_VALUE.NORM_SCALE PARAM_VALUE.NORM_SCALE } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.NORM_SCALE}] ${MODELPARAM_VALUE.NORM_SCALE}
}

proc update_MODELPARAM_VALUE.ACC_W { MODELPARAM_VALUE.ACC_W PARAM_VALUE.ACC_W } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.ACC_W}] ${MODELPARAM_VALUE.ACC_W}
}

proc update_MODELPARAM_VALUE.MAX_W { MODELPARAM_VALUE.MAX_W PARAM_VALUE.MAX_W } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.MAX_W}] ${MODELPARAM_VALUE.MAX_W}
}

proc update_MODELPARAM_VALUE.ADDR_AW { MODELPARAM_VALUE.ADDR_AW PARAM_VALUE.ADDR_AW } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.ADDR_AW}] ${MODELPARAM_VALUE.ADDR_AW}
}

