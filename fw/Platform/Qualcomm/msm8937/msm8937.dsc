## @file
#  SoC-платформа MSM8937 / MSM8940 (Snapdragon 430/435) для edk2-msm.
#
#  Отличия от sdm660 (на котором построен этот шаблон):
#   * GICv2 (qgic2: dist 0x0B000000, cpu-interface 0x0B002000), а не GICv3;
#   * eMMC через SDCC (sdhci@7824900), а не UFS;
#   * UART — QUP v1.4 (BLSP1 UART2), а не GENI;
#   * сплэш-фреймбуфер LK остаётся в RAM по 0x90000000.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##
[Defines]
  SOC_PLATFORM            = MSM8937
  USE_PHYSICAL_TIMER      = TRUE

!include Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc

[PcdsFixedAtBuild.common]
  # ── DDR (по /proc/iomem устройства) ─────────────────────────────────────
  # System RAM: 0x10000000-0x849FFFFF и 0x8EA00000-0xFFFFFFFF
  gArmTokenSpaceGuid.PcdSystemMemoryBase|0x10000000
  gArmTokenSpaceGuid.PcdSystemMemorySize|0xF0000000

  # ── PrePi/секция до DXE (см. PlatformMemoryMapLib.c) ───────────────────
  gArmTokenSpaceGuid.PcdCpuVectorBaseAddress|0x8F280000
  gEmbeddedTokenSpaceGuid.PcdPrePiStackBase|0x8F290000
  gEmbeddedTokenSpaceGuid.PcdPrePiStackSize|0x00040000

  # ── Таймер и GICv2 ─────────────────────────────────────────────────────
  gArmTokenSpaceGuid.PcdArmArchTimerFreqInHz|19200000
  # PPI 13/14 (secure/non-secure physical) -> GIC IRQ id 29/30.
  # TODO: уточнить по живой системе (UART-лог).
  gArmTokenSpaceGuid.PcdArmArchTimerSecIntrNum|29
  gArmTokenSpaceGuid.PcdArmArchTimerIntrNum|30
  gArmTokenSpaceGuid.PcdGicDistributorBase|0x0B000000
  gArmTokenSpaceGuid.PcdGicInterruptInterfaceBase|0x0B002000

  # ── DXE heap / фреймбуфер ──────────────────────────────────────────────
  gQcomTokenSpaceGuid.PcdUefiMemPoolBase|0x92000000
  gQcomTokenSpaceGuid.PcdUefiMemPoolSize|0x0E000000
  gQcomTokenSpaceGuid.PcdMipiFrameBufferAddress|0x90000000

  # ── CPU: 4x A53 (SD430) или 8x A53 одним кластером (SD435) ─────────────
  gArmPlatformTokenSpaceGuid.PcdCoreCount|8
  gArmPlatformTokenSpaceGuid.PcdClusterCount|1

  gEfiMdeModulePkgTokenSpaceGuid.PcdAcpiDefaultOemRevision|0x00000850
  gEmbeddedTokenSpaceGuid.PcdPrePiCpuIoSize|44

  #
  # SimpleInit
  #
  gSimpleInitTokenSpaceGuid.PcdDeviceTreeStore|0x8F2E0000
  gSimpleInitTokenSpaceGuid.PcdLoggerdUseConsole|FALSE

[LibraryClasses.common]
  AslUpdateLib|Silicon/Qualcomm/QcomPkg/Library/DxeAslUpdateLib/DxeAslUpdateLib.inf

  PlatformMemoryMapLib|Silicon/Qualcomm/msm8937/Library/PlatformMemoryMapLib/PlatformMemoryMapLib.inf
  PlatformPeiLib|Silicon/Qualcomm/msm8937/Library/PlatformPeiLib/PlatformPeiLib.inf
  PlatformPrePiLib|Silicon/Qualcomm/msm8937/Library/PlatformPrePiLib/PlatformPrePiLib.inf
  MsPlatformDevicesLib|Silicon/Qualcomm/msm8937/Library/MsPlatformDevicesLib/MsPlatformDevicesLib.inf
  SOCSmbiosInfoLib|Silicon/Qualcomm/msm8937/Library/SOCSmbiosInfoLib/SOCSmbiosInfoLib.inf

  # QcomGeniSerialPortLib из QcomPkg — GENI, на msm8937 не работает.
!if $(USE_UART) == 1
  SerialPortLib|Silicon/Qualcomm/QcomPkg/Library/MsmUartSerialPortLib/MsmUartSerialPortLib.inf
!endif

[Components.common]
