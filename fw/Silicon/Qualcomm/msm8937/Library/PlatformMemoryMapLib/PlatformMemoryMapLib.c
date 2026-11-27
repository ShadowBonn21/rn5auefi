// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// PlatformMemoryMapLib для Qualcomm MSM8940 (Snapdragon 435), Xiaomi ugg.
//
// ВСЕ АДРЕСА DDR СНЯТЫ С ЖИВОГО УСТРОЙСТВА (adb root):
//   /proc/iomem :  System RAM 0x10000000-0x849FFFFF
//                  System RAM 0x8EA00000-0xFFFFFFFF
//   DTB reserved-memory (build/ugg.dtb):
//                  other_ext_region  0x84A00000 + 0x1E00000
//                  modem_region      0x86800000 + 0x6A00000
//                  adsp_fw_region    0x8D200000 + 0x1100000
//                  wcnss_fw_region   0x8E300000 + 0x700000
//                  splash_region     0x90000000 + 0x1400000
//
// ВАЖНО: dtsi из CAF-исходников даёт ДРУГИЕ размеры (modem 0x5000000,
// adsp 0x8B800000...). Доверять нужно этим, снятым с конкретной ревизии.
//
#include <Library/BaseLib.h>
#include <Library/PlatformMemoryMapLib.h>

STATIC ARM_MEMORY_REGION_DESCRIPTOR_EX gDeviceMemoryDescriptorEx[] = {
  /* Name               Address     Length      HobOption  ResourceAttribute   ArmAttributes
                                                        ResourceType  MemoryType */

  /* ─── DDR: нижнее окно (System RAM по iomem) ─────────────────────────── */
  // 0x10000000..0x84A00000. LK грузит boot.img в 0x80008000 — эта часть
  // верхнего края используется под наш образ, остальное свободно.
  {"RAM Partition",     0x10000000, 0x74A00000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},

  /* ─── reserved-memory из DTB устройства ──────────────────────────────── */
  {"OTHER_EXT",         0x84A00000, 0x01E00000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, UNCACHED_UNBUFFERED_XN},
  {"MODEM",             0x86800000, 0x06A00000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, UNCACHED_UNBUFFERED_XN},
  {"ADSP FW",           0x8D200000, 0x01100000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, UNCACHED_UNBUFFERED_XN},
  {"WCNSS FW",          0x8E300000, 0x00700000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, UNCACHED_UNBUFFERED_XN},

  /* ─── окно под UEFI: 0x8EA00000..0x90000000 (22 МиБ свободны) ─────────── */
  // FD_BASE/FD_SIZE должны совпадать с configs/msm8937.conf
  {"UEFI FD",           0x8EA00000, 0x00800000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK},
  {"SEC Heap",          0x8F200000, 0x00080000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"CPU Vectors",       0x8F280000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK},
  {"MMU PageTables",    0x8F281000, 0x00003000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"UEFI Stack",        0x8F290000, 0x00040000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"Info Blk",          0x8F2D0000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, WRITE_BACK_XN},

  /* ─── Сплэш-LK = наш framebuffer (32bpp, stride 2944, 2 буфера) ────────── */
  // 720*2944*2 = 7 536 640 байт из 20 МиБ региона.
  // ВАЖНО: начинаем на 0x8FFF0000, а не с 0x90000000 — драйвер рисует с
  // 0x8FFFFF00 (сдвиг сканирования MDSS 256 байт). Не отображённые страницы
  // дали бы data abort на первой же записи пикселя.
  {"Display Reserved",  0x8FFF0000, 0x01500000, AddMem, MEM_RES, SYS_MEM_CAP, Reserv, WRITE_THROUGH_XN},

  /* ─── DDR: верхнее окно ──────────────────────────────────────────────── */
  {"DXE Heap",          0x92000000, 0x0E000000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},
  {"RAM Partition",     0xA0000000, 0x60000000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},

  /* ─── MMIO ───────────────────────────────────────────────────────────── */
  {"BLSP1 (UART2)",     0x07880000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SDHC1 (eMMC)",      0x07824900, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SDHC2 (SD)",        0x07864900, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"USB3 (dwc3)",       0x078D9000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"TLMM",              0x01000000, 0x00300000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GCC CLK CTL",       0x01800000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MDSS",              0x01A00000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SPMI",              0x0200F000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  /*
    Окна SPMI-арбитра. Без них обращение к каналам и таблице mapping даёт
    отказ трансляции (и перезагрузку устройства), поэтому обязательны
    для работы с PMIC (питание eMMC, кнопки PON).
  */
  {"SPMI CFG",          0x0200A000, 0x00002100, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SPMI CHNLS",        0x02400000, 0x00800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SPMI OBSRVR",       0x02C00000, 0x00800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"RPM MSG RAM",       0x00068000, 0x00008000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SECURITY CONTROL",  0x00780000, 0x00007000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QDSS",              0x06080000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"IMEM",              0x14680000, 0x00040000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"IMEM COOKIE",       0x146BF000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QTIMER",            0x0B120000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GIC DIST",          0x0B000000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GIC CPU IF",        0x0B002000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},

  /* Терминатор — обязателен. */
  {"Terminator",        0,          0,          0,      0,       0,           0,       0}
};

ARM_MEMORY_REGION_DESCRIPTOR_EX *
GetPlatformMemoryMap (
  VOID
  )
{
  return gDeviceMemoryDescriptorEx;
}
