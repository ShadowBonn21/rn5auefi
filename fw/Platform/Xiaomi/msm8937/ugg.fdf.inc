// Устройство ugg (Redmi Note 5A Prime): device-specific содержимое FV.
//
// ACPI: таблиц для msm8937 у нас нет и не будет (Windows on ARM-путь закрыт),
// поэтому секция ACPI не заполняется — Linux пойдёт через Device Tree.
//
// SPDX-License-Identifier: BSD-2-Clause-Patent

// Mainline device tree, отдаваемый загрузчику ОС (LinuxLoader/GRUB).
// Положить сюда DTB, собранный из msm8937-ugg.dts (см. docs/03-dumps.md),
// либо оставить пустым: тогда UEFI возьмёт DTB, который передал LK.
// FILE FREEFORM = <ваш-guid> {
//   SECTION RAW = Platform/Xiaomi/ugg/FdtBlob/ugg.dtb
//   SECTION UI  = "Device Tree"
// }
