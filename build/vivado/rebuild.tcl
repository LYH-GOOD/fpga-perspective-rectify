# Source from Vivado 2025.2 Tcl console or Vivado MCP run_tcl.
# Project paths are relative to this file. This script creates targets; it does not launch runs.
# ── 本仓库改动（2026-11-02，相对队友原版；原版备份见存档）──────────────
# RTL 源不再在 vivado/ 下另存一份，直接指向仓库唯一的 src/rtl/
# （否则 axis_light27.v 会有两份，迟早漂移）。hdmi_out.xdc 也在那里。
set root [file dirname [file normalize [info script]]]
set build [file join $root build]
set src [file normalize [file join $root .. .. src rtl]]
if {[file exists $build]} {error {build exists; choose a fresh source extraction}}

if {[version -short] ne {2025.2}} {error {Vivado 2025.2 required}}

create_project p11_light27 $build -part xc7z020clg400-1
set_property ip_repo_paths [list [file join $root ip_repo]] [current_project]
update_ip_catalog
add_files [list [file join $src axis_bypass.v] [file join $src axis_bypass_bd.v] [file join $src axis_light27.v]]
source [file join $root system_light27.tcl]
validate_bd_design
save_bd_design
add_files -fileset constrs_1 [file join $src hdmi_out.xdc]
generate_target all [get_files system.bd]
set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
puts {Project prepared. Run synthesis and implementation, inspect reports, then generate bitstream and export XSA.}
