## @file
#  РЈСЃС‚СЂРѕР№СЃС‚РІРѕ: Xiaomi Redmi Note 5A Prime (ugg / MSM8940), 4/64, 720x1280.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##
[Defines]
  VENDOR_NAME                    = Xiaomi
  PLATFORM_NAME                  = ugg
  PLATFORM_GUID                  = 0d6a51c4-31f7-4b9e-a2c8-5f0d7e91b344
  PLATFORM_VERSION               = 0.1
  DSC_SPECIFICATION              = 0x00010019
  OUTPUT_DIRECTORY               = Build/$(PLATFORM_NAME)
  SUPPORTED_ARCHITECTURES        = AARCH64
  BUILD_TARGETS                  = DEBUG|RELEASE
  SKUID_IDENTIFIER               = DEFAULT
  FLASH_DEFINITION               = Platform/Qualcomm/msm8937/msm8937.fdf
  DEVICE_DXE_FV_COMPONENTS       = Platform/Xiaomi/msm8937/ugg.fdf.inc

!include Platform/Qualcomm/msm8937/msm8937.dsc

[BuildOptions.common]
  GCC:*_*_AARCH64_CC_FLAGS = -DENABLE_SIMPLE_INIT

[PcdsFixedAtBuild.common]
  # Панель ugg: 720x1280, MDSS 32bpp, stride 2944 (fb0/stride), 2 буфера
  gQcomTokenSpaceGuid.PcdMipiFrameBufferWidth|720
  gQcomTokenSpaceGuid.PcdMipiFrameBufferHeight|1280
  gQcomTokenSpaceGuid.PcdMipiFrameBufferAddress|0x90000000
  gMsm8937PkgTokenSpaceGuid.PcdFbStride|2160
  gMsm8937PkgTokenSpaceGuid.PcdFbRgbOrder|0

  # Simple Init
  gSimpleInitTokenSpaceGuid.PcdGuiDefaultDPI|320

  gRenegadePkgTokenSpaceGuid.PcdDeviceVendor|"Redmi"
  gRenegadePkgTokenSpaceGuid.PcdDeviceProduct|"Note 5A Prime"
  gRenegadePkgTokenSpaceGuid.PcdDeviceCodeName|"ugg"

