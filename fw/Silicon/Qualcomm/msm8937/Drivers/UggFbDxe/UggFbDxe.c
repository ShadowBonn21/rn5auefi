/** @file
  UggFbDxe — драйвер framebuffer для Xiaomi Redmi Note 5A Prime (ugg / MSM8940).

  Зачем свой, если в edk2-msm есть SimpleFbDxe:
    * панель ugg отдаёт 24 бита на пиксель (qcom,mdss-dsi-bpp = 0x18 в DTB,
      подтверждено экспериментом: ровная рамка только при 24bpp);
    * шаг строки у сплэша LK — 2160 байт (ровно 720*3, без выравнивания);
    * SimpleFbDxe жёстко зашит на 32bpp (PixelBlueGreenRedReserved8BitPerColor)
      и использует FrameBufferBltLib, который тоже только 32-битный.

  Поэтому здесь: GOP отдаёт «как есть» 720x1280, а внутри каждый пиксель
  конвертируется из 32bpp BGRA (формат GOP) в 3 байта (RGB или BGR — PCD).

  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PcdLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Protocol/DevicePath.h>
#include <Protocol/GraphicsOutput.h>

/* Порядок байтов в памяти: 0 = R,G,B ; 1 = B,G,R. Уточняется PCD. */
#define FB_ORDER_RGB  0
#define FB_ORDER_BGR  1

/*
  Панель ugg: MDSS сканирует на 256 байт РАНЬШЕ 0x90000000 — измерено по фото
  (рамка-тест ложится по краям панели с точностью ~±5 px). Поэтому рисуем с
  0x90000000 - 256 = 0x8FFFFF00, чтобы координата GOP x=0 попала ровно в левый
  край панели. PcdFbXShiftBytes обязан быть кратен 4: иначе 32-битные записи в
  Device-память дают alignment fault (проверено — payload падал).
*/
#define FB_BASE  ((UINTN)(FixedPcdGet32 (PcdMipiFrameBufferAddress) - FixedPcdGet32 (PcdFbXShiftBytes)))

typedef struct {
  EFI_GRAPHICS_OUTPUT_PROTOCOL          Gop;
  EFI_GRAPHICS_OUTPUT_PROTOCOL_MODE     Mode;
  EFI_GRAPHICS_OUTPUT_MODE_INFORMATION  Info;
} UGG_FB;

STATIC UGG_FB  mUggFb;
STATIC UINT8   mDummyDevicePath[] = {
  0x02, 0x01, 0x0C, 0x00,              /* ACPI DP: HID = ... */
  0x41, 0x43, 0x50, 0x49, 0x5F, 0x46, 0x42, 0x30, 0x30, 0x30, 0x30, 0x00,
  0x7F, 0xFF, 0x04, 0x00               /* End of Device Path */
};

STATIC UINTN
FbStride (
  VOID
  )
{
  return (UINTN)FixedPcdGet32 (PcdFbStride);
}

STATIC UINT8 *
FbPixelPtr (
  IN UINTN  X,
  IN UINTN  Y
  )
{
  return (UINT8 *)(FB_BASE + Y * FbStride () + X * 3);
}

STATIC VOID
FbPutPixel (
  IN UINTN                          X,
  IN UINTN                          Y,
  IN EFI_GRAPHICS_OUTPUT_BLT_PIXEL  *Pixel
  )
{
  UINT8  *P = FbPixelPtr (X, Y);

  if (FixedPcdGet32 (PcdFbRgbOrder) == FB_ORDER_BGR) {
    P[0] = Pixel->Blue;
    P[1] = Pixel->Green;
    P[2] = Pixel->Red;
  } else {
    P[0] = Pixel->Red;
    P[1] = Pixel->Green;
    P[2] = Pixel->Blue;
  }
}

STATIC VOID
FbGetPixel (
  IN  UINTN                          X,
  IN  UINTN                          Y,
  OUT EFI_GRAPHICS_OUTPUT_BLT_PIXEL  *Pixel
  )
{
  UINT8  *P = FbPixelPtr (X, Y);

  if (FixedPcdGet32 (PcdFbRgbOrder) == FB_ORDER_BGR) {
    Pixel->Blue  = P[0];
    Pixel->Green = P[1];
    Pixel->Red   = P[2];
  } else {
    Pixel->Red   = P[0];
    Pixel->Green = P[1];
    Pixel->Blue  = P[2];
  }
  Pixel->Reserved = 0;
}

STATIC VOID
FbFillRect (
  IN UINTN                          X,
  IN UINTN                          Y,
  IN UINTN                          Width,
  IN UINTN                          Height,
  IN EFI_GRAPHICS_OUTPUT_BLT_PIXEL  *Pixel
  )
{
  UINTN  Row;
  UINTN  Col;
  UINT8  *Ptr;

  for (Row = 0; Row < Height; Row++) {
    Ptr = FbPixelPtr (X, Y + Row);
    for (Col = 0; Col < Width; Col++) {
      if (FixedPcdGet32 (PcdFbRgbOrder) == FB_ORDER_BGR) {
        Ptr[0] = Pixel->Blue;
        Ptr[1] = Pixel->Green;
        Ptr[2] = Pixel->Red;
      } else {
        Ptr[0] = Pixel->Red;
        Ptr[1] = Pixel->Green;
        Ptr[2] = Pixel->Blue;
      }
      Ptr += 3;
    }
  }
}

/**
  Блит в framebuffer. Поддерживаются операции, которыми реально пользуются
  UEFI-консоль (GraphicsConsoleDxe), SimpleInit и GRUB.

  @retval EFI_SUCCESS            выполнено
  @retval EFI_INVALID_PARAMETER  выход за границы
  @retval EFI_UNSUPPORTED        неподдерживаемая операция
**/
STATIC EFI_STATUS
EFIAPI
UggFbBlt (
  IN EFI_GRAPHICS_OUTPUT_PROTOCOL       *This,
  IN EFI_GRAPHICS_OUTPUT_BLT_PIXEL      *BltBuffer OPTIONAL,
  IN EFI_GRAPHICS_OUTPUT_BLT_OPERATION  BltOperation,
  IN UINTN                              SourceX,
  IN UINTN                              SourceY,
  IN UINTN                              DestinationX,
  IN UINTN                              DestinationY,
  IN UINTN                              Width,
  IN UINTN                              Height,
  IN UINTN                              Delta OPTIONAL
  )
{
  UINTN                          W = FixedPcdGet32 (PcdMipiFrameBufferWidth);
  UINTN                          H = FixedPcdGet32 (PcdMipiFrameBufferHeight);
  UINTN                          Row;
  UINTN                          Col;
  UINTN                          BltDelta;
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Pixel;

  if ((Width == 0) || (Height == 0)) {
    return EFI_SUCCESS;
  }

  switch (BltOperation) {
  case EfiBltVideoFill:
    if (BltBuffer == NULL) {
      return EFI_INVALID_PARAMETER;
    }
    FbFillRect (DestinationX, DestinationY, Width, Height, BltBuffer);
    return EFI_SUCCESS;

  case EfiBltBufferToVideo:
    if (BltBuffer == NULL) {
      return EFI_INVALID_PARAMETER;
    }
    BltDelta = (Delta == 0) ? (Width * sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL)) : Delta;
    if ((DestinationX + Width > W) || (DestinationY + Height > H)) {
      return EFI_INVALID_PARAMETER;
    }
    for (Row = 0; Row < Height; Row++) {
      for (Col = 0; Col < Width; Col++) {
        CopyMem (
          &Pixel,
          (UINT8 *)BltBuffer + (SourceY + Row) * BltDelta +
          (SourceX + Col) * sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL),
          sizeof (Pixel)
          );
        FbPutPixel (DestinationX + Col, DestinationY + Row, &Pixel);
      }
    }
    return EFI_SUCCESS;

  case EfiBltVideoToBltBuffer:
    if (BltBuffer == NULL) {
      return EFI_INVALID_PARAMETER;
    }
    BltDelta = (Delta == 0) ? (Width * sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL)) : Delta;
    for (Row = 0; Row < Height; Row++) {
      for (Col = 0; Col < Width; Col++) {
        FbGetPixel (SourceX + Col, SourceY + Row, &Pixel);
        CopyMem (
          (UINT8 *)BltBuffer + (DestinationY + Row) * BltDelta +
          (DestinationX + Col) * sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL),
          &Pixel,
          sizeof (Pixel)
          );
      }
    }
    return EFI_SUCCESS;

  case EfiBltVideoToVideo:
    if ((SourceX + Width > W) || (SourceY + Height > H) ||
        (DestinationX + Width > W) || (DestinationY + Height > H))
    {
      return EFI_INVALID_PARAMETER;
    }
    /* копируем построчно, направление — на случай перекрытия */
    for (Row = 0; Row < Height; Row++) {
      UINTN DstRow = (DestinationY > SourceY) ? (Height - 1 - Row) : Row;
      for (Col = 0; Col < Width; Col++) {
        UINTN DstCol = (DestinationX > SourceX) ? (Width - 1 - Col) : Col;
        FbGetPixel (SourceX + DstCol, SourceY + DstRow, &Pixel);
        FbPutPixel (DestinationX + DstCol, DestinationY + DstRow, &Pixel);
      }
    }
    return EFI_SUCCESS;

  default:
    return EFI_UNSUPPORTED;
  }
}

STATIC EFI_STATUS
EFIAPI
UggFbQueryMode (
  IN  EFI_GRAPHICS_OUTPUT_PROTOCOL          *This,
  IN  UINT32                               ModeNumber,
  OUT UINTN                                *SizeOfInfo,
  OUT EFI_GRAPHICS_OUTPUT_MODE_INFORMATION  **Info
  )
{
  *SizeOfInfo = sizeof (EFI_GRAPHICS_OUTPUT_MODE_INFORMATION);
  *Info       = AllocateCopyPool (*SizeOfInfo, &mUggFb.Info);
  if (*Info == NULL) {
    return EFI_OUT_OF_RESOURCES;
  }
  return EFI_SUCCESS;
}

STATIC EFI_STATUS
EFIAPI
UggFbSetMode (
  IN EFI_GRAPHICS_OUTPUT_PROTOCOL  *This,
  IN UINT32                        ModeNumber
  )
{
  return (ModeNumber == 0) ? EFI_SUCCESS : EFI_UNSUPPORTED;
}

/* Точка входа: НЕ static — edk2 генерирует для неё внешний прототип из INF. */
EFI_STATUS
EFIAPI
UggFbDxeInitialize (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  EFI_STATUS                            Status;
  EFI_HANDLE                            Handle = NULL;
  UINTN                                 Width  = FixedPcdGet32 (PcdMipiFrameBufferWidth);
  UINTN                                 Height = FixedPcdGet32 (PcdMipiFrameBufferHeight);
  UINTN                                 Base   = FB_BASE;
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL         Black  = { 0, 0, 0, 0 };

  DEBUG ((EFI_D_INFO,
    "UggFbDxe: base=0x%08x (pcd 0x%08x shift %d B) %dx%d stride=%d order=%d\n",
    (UINT32)Base, (UINT32)FixedPcdGet32 (PcdMipiFrameBufferAddress),
    (UINT32)FixedPcdGet32 (PcdFbXShiftBytes), (UINT32)Width, (UINT32)Height,
    (UINT32)FbStride (), (UINT32)FixedPcdGet32 (PcdFbRgbOrder)));

  if ((Base == 0) || (Width == 0) || (Height == 0)) {
    DEBUG ((EFI_D_ERROR, "UggFbDxe: invalid PCDs\n"));
    return EFI_DEVICE_ERROR;
  }

  ZeroMem (&mUggFb, sizeof (mUggFb));

  mUggFb.Info.Version               = 0;
  mUggFb.Info.HorizontalResolution  = (UINT32)Width;
  mUggFb.Info.VerticalResolution    = (UINT32)Height;
  mUggFb.Info.PixelFormat           = PixelBlueGreenRedReserved8BitPerColor;
  /* логическая ширина строки = width; физическая — PcdFbStride/3 */
  mUggFb.Info.PixelsPerScanLine     = (UINT32)Width;

  mUggFb.Mode.MaxMode       = 1;
  mUggFb.Mode.Mode          = 0;
  mUggFb.Mode.Info          = &mUggFb.Info;
  mUggFb.Mode.SizeOfInfo    = sizeof (mUggFb.Info);
  mUggFb.Mode.FrameBufferBase = Base;
  mUggFb.Mode.FrameBufferSize = FbStride () * Height;

  mUggFb.Gop.QueryMode = UggFbQueryMode;
  mUggFb.Gop.SetMode   = UggFbSetMode;
  mUggFb.Gop.Blt       = UggFbBlt;
  mUggFb.Gop.Mode      = &mUggFb.Mode;

  /* Экран чистый: иначе на нём останется сплэш LK под текстом консоли. */
  FbFillRect (0, 0, Width, Height, &Black);

  /*
    Отладочная метка: белая полоса на 50-й строке (GOP установлен).
    Видна => драйвер дошёл до конца инициализации (GOP установлен).
    Убрать вместе с fw/patches/paint_stages.py, когда UEFI заработает.
  */
  if (FixedPcdGet32 (PcdDebugStageBands) != 0) {
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL  White = { 0xFF, 0xFF, 0xFF, 0 };

    FbFillRect (0, 50, Width, 40, &White);
  }

  Status = gBS->InstallMultipleProtocolInterfaces (
                  &Handle,
                  &gEfiGraphicsOutputProtocolGuid,
                  &mUggFb.Gop,
                  &gEfiDevicePathProtocolGuid,
                  (EFI_DEVICE_PATH_PROTOCOL *)mDummyDevicePath,
                  NULL
                  );
  ASSERT_EFI_ERROR (Status);
  return Status;
}
