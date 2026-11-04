# 把 rebuild.tcl 建好的工程跑到位流，并导出报告与 XSA。
#
# 用法（在 build/vivado/ 目录下，且 rebuild.tcl 已成功跑过）：
#     vivado -mode batch -source run_build.tcl -nojournal -log run_build.log
#
# 前置：同目录下必须有 rebuild.tcl 生成的 build/p11_light27.xpr。
#       rebuild.tcl 只建目标不跑流程，两步是分开的——这样建工程失败和构建失败
#       不会混在同一条日志里。
#
# 产物：
#     build/p11_light27.runs/impl_1/system_wrapper.bit   位流
#     reports/*.rpt                                       9 份 *_impl.rpt（另 1 份 synth_utilization.rpt）
#     p11_light27.xsa                                     硬件平台
#
# 这一步耗时以小时计的话说明 jobs 太小；Zynq-7020 这个规模 8 jobs 约半小时。

set root [file dirname [file normalize [info script]]]
set proj [file join $root build p11_light27.xpr]
set rep  [file join $root reports]

if {![file exists $proj]} {
    error "找不到 $proj —— 先跑 rebuild.tcl 把工程建出来"
}
file mkdir $rep

set jobs [expr {[info exists ::env(NPROC)] ? $::env(NPROC) : 8}]
puts "INFO: jobs = $jobs"

open_project $proj

# ── 综合 ────────────────────────────────────────────────────────────────
puts "INFO: launch_runs synth_1"
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "综合失败：PROGRESS = [get_property PROGRESS [get_runs synth_1]]，看日志"
}
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "综合状态异常：[get_property STATUS [get_runs synth_1]]"
}
open_run synth_1 -name synth_1
report_utilization -file [file join $rep synth_utilization.rpt]
puts "INFO: 综合完成"

# ── 实现到写位流 ────────────────────────────────────────────────────────
puts "INFO: launch_runs impl_1 -to_step write_bitstream"
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "实现失败：PROGRESS = [get_property PROGRESS [get_runs impl_1]]，看日志"
}
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "实现状态异常：[get_property STATUS [get_runs impl_1]]"
}
puts "INFO: 实现完成"

open_run impl_1

# ── 报告：文件名沿用 build/reports 的旧约定，便于对比 ───────────────────
report_utilization              -file [file join $rep utilization_impl.rpt]
report_utilization -hierarchical -file [file join $rep utilization_impl_hier.rpt]
report_timing_summary           -file [file join $rep timing_impl.rpt]
report_clock_utilization        -file [file join $rep clocks_impl.rpt]
report_io                       -file [file join $rep io_impl.rpt]
report_drc                      -file [file join $rep drc_impl.rpt]
check_timing                    -file [file join $rep check_timing_impl.rpt]
# 这两份 handoff 里有、旧 build/reports 没有，顺手带上
report_power                    -file [file join $rep power_impl.rpt]
report_route_status             -file [file join $rep route_status_impl.rpt]
puts "INFO: 报告已写入 $rep"

# ── 位流与 XSA ──────────────────────────────────────────────────────────
set bit [glob -nocomplain [file join $root build p11_light27.runs impl_1 *.bit]]
if {[llength $bit] == 0} { error "没找到 .bit —— write_bitstream 没产出" }
puts "INFO: bitstream = [lindex $bit 0]"
write_hw_platform -fixed -include_bit -force -file [file join $root p11_light27.xsa]
puts "INFO: xsa = [file join $root p11_light27.xsa]"

puts "BUILD_DONE"
close_project
