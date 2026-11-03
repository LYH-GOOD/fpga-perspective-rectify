// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2025.2 (64-bit)
// Tool Version Limit: 2025.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xaxis_sharp.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XAxis_sharp_CfgInitialize(XAxis_sharp *InstancePtr, XAxis_sharp_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XAxis_sharp_Start(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL) & 0x80;
    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XAxis_sharp_IsDone(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XAxis_sharp_IsIdle(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XAxis_sharp_IsReady(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XAxis_sharp_EnableAutoRestart(XAxis_sharp *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XAxis_sharp_DisableAutoRestart(XAxis_sharp *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_AP_CTRL, 0);
}

void XAxis_sharp_Set_w_out(XAxis_sharp *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_W_OUT_DATA, Data);
}

u32 XAxis_sharp_Get_w_out(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_W_OUT_DATA);
    return Data;
}

void XAxis_sharp_Set_h_out(XAxis_sharp *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_H_OUT_DATA, Data);
}

u32 XAxis_sharp_Get_h_out(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_H_OUT_DATA);
    return Data;
}

void XAxis_sharp_Set_a8(XAxis_sharp *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_A8_DATA, Data);
}

u32 XAxis_sharp_Get_a8(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_A8_DATA);
    return Data;
}

void XAxis_sharp_Set_enable(XAxis_sharp *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_ENABLE_DATA, Data);
}

u32 XAxis_sharp_Get_enable(XAxis_sharp *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_ENABLE_DATA);
    return Data;
}

void XAxis_sharp_InterruptGlobalEnable(XAxis_sharp *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_GIE, 1);
}

void XAxis_sharp_InterruptGlobalDisable(XAxis_sharp *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_GIE, 0);
}

void XAxis_sharp_InterruptEnable(XAxis_sharp *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_IER);
    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_IER, Register | Mask);
}

void XAxis_sharp_InterruptDisable(XAxis_sharp *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_IER);
    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_IER, Register & (~Mask));
}

void XAxis_sharp_InterruptClear(XAxis_sharp *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XAxis_sharp_WriteReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_ISR, Mask);
}

u32 XAxis_sharp_InterruptGetEnabled(XAxis_sharp *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_IER);
}

u32 XAxis_sharp_InterruptGetStatus(XAxis_sharp *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XAxis_sharp_ReadReg(InstancePtr->Control_BaseAddress, XAXIS_SHARP_CONTROL_ADDR_ISR);
}

