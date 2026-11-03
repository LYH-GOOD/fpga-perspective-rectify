// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2025.2 (64-bit)
// Tool Version Limit: 2025.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XAXIS_SHARP_H
#define XAXIS_SHARP_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xaxis_sharp_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Control_BaseAddress;
} XAxis_sharp_Config;
#endif

typedef struct {
    u64 Control_BaseAddress;
    u32 IsReady;
} XAxis_sharp;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XAxis_sharp_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XAxis_sharp_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XAxis_sharp_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XAxis_sharp_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XAxis_sharp_Initialize(XAxis_sharp *InstancePtr, UINTPTR BaseAddress);
XAxis_sharp_Config* XAxis_sharp_LookupConfig(UINTPTR BaseAddress);
#else
int XAxis_sharp_Initialize(XAxis_sharp *InstancePtr, u16 DeviceId);
XAxis_sharp_Config* XAxis_sharp_LookupConfig(u16 DeviceId);
#endif
int XAxis_sharp_CfgInitialize(XAxis_sharp *InstancePtr, XAxis_sharp_Config *ConfigPtr);
#else
int XAxis_sharp_Initialize(XAxis_sharp *InstancePtr, const char* InstanceName);
int XAxis_sharp_Release(XAxis_sharp *InstancePtr);
#endif

void XAxis_sharp_Start(XAxis_sharp *InstancePtr);
u32 XAxis_sharp_IsDone(XAxis_sharp *InstancePtr);
u32 XAxis_sharp_IsIdle(XAxis_sharp *InstancePtr);
u32 XAxis_sharp_IsReady(XAxis_sharp *InstancePtr);
void XAxis_sharp_EnableAutoRestart(XAxis_sharp *InstancePtr);
void XAxis_sharp_DisableAutoRestart(XAxis_sharp *InstancePtr);

void XAxis_sharp_Set_w_out(XAxis_sharp *InstancePtr, u32 Data);
u32 XAxis_sharp_Get_w_out(XAxis_sharp *InstancePtr);
void XAxis_sharp_Set_h_out(XAxis_sharp *InstancePtr, u32 Data);
u32 XAxis_sharp_Get_h_out(XAxis_sharp *InstancePtr);
void XAxis_sharp_Set_a8(XAxis_sharp *InstancePtr, u32 Data);
u32 XAxis_sharp_Get_a8(XAxis_sharp *InstancePtr);
void XAxis_sharp_Set_enable(XAxis_sharp *InstancePtr, u32 Data);
u32 XAxis_sharp_Get_enable(XAxis_sharp *InstancePtr);

void XAxis_sharp_InterruptGlobalEnable(XAxis_sharp *InstancePtr);
void XAxis_sharp_InterruptGlobalDisable(XAxis_sharp *InstancePtr);
void XAxis_sharp_InterruptEnable(XAxis_sharp *InstancePtr, u32 Mask);
void XAxis_sharp_InterruptDisable(XAxis_sharp *InstancePtr, u32 Mask);
void XAxis_sharp_InterruptClear(XAxis_sharp *InstancePtr, u32 Mask);
u32 XAxis_sharp_InterruptGetEnabled(XAxis_sharp *InstancePtr);
u32 XAxis_sharp_InterruptGetStatus(XAxis_sharp *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
