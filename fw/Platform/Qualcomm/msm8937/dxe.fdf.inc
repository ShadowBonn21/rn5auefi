#  Платформенные DXE-драйверы msm8937.
#
#  ВАЖНО. На apstream-ветке edk2-msm драйверы SoC поставляются ГОТОВЫМИ
#  бинарями из сабмодуля Platform/EFI_Binaries (edk2-msm-binary), отдельно для
#  каждого SoC. Для msm8937 таких бинарей НЕТ. Ниже — что именно требуется,
#  и в каком статусе это находится:
#
#   SdccDxe        eMMC (sdhci@7824900)      -- НАПИСАТЬ (главный блокер, G3)
#   UsbInitDxe     инициализация USB3 PHY    -- НАПИСАТЬ
#   UsbConfigDxe   роль/скорость USB         -- НАПИСАТЬ
#   DALTLMM        GPIO                      -- НАПИСАТЬ (нужен для кнопок)
#   SPMI/PmicDxe   PMIC  (pmi8950)           -- НАПИСАТЬ (кнопки/зарядка/LDO)
#   ClockDxe       GCC/RPM-клоки             -- НАПИСАТЬ (нужен для SDCC)
#
#  Для первого дешёвого шага (G1: UEFI Shell на экране) они НЕ нужны:
#  PrePi + DXE core + ARM GIC/Timer + SimpleFbDxe достаточно.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent

# --- G1: без SoC-бинарей ------------------------------------------------
# (ничего не добавляем; консоль на framebuffer уже включена в основном FDF)

# --- G3+: сюда добавлять по мере написания своих драйверов --------------
# FILE DRIVER = <guid> {
#   SECTION DXE_DEPEX = Platform/Qualcomm/msm8937/Drivers/SdccDxe/SdccDxe.depex
#   SECTION PE32      = $(OUT_DIR)/AARCH64/SdccDxe.efi
#   SECTION UI        = "SdccDxe (eMMC)"
# }
