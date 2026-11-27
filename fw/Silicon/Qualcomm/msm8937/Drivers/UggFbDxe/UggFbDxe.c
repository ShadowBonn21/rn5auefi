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
/*
  Device path для GOP-хэндла: узел ACPI (Type 0x02, SubType 0x01).

  ВНИМАНИЕ: раньше здесь был узел с Length = 0x0C, хотя ACPI-узел занимает
  16 байт (заголовок 4 + HID 8 + UID 4). Неверная длина ломала разбор
  device path: InstallMultipleProtocolInterfaces не возвращался, GOP не
  устанавливался, и BDS навсегда оставался с чёрным экраном.
*/
STATIC UINT8  mFbDevicePath[] = {
  0x02, 0x01, 0x10, 0x00,              /* Type=ACPI(0x02) SubType=ACPI(0x01) Len=16 */
  'A', 'C', 'P', 'I', '_', 'F', 'B', '0',   /* HID, 8 байт */
  0x00, 0x00, 0x00, 0x00,              /* UID */
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

/* Отладка: периодическая перерисовка креста (PcdDebugStageBands == 2). */
STATIC EFI_EVENT  mRedrawTimer = NULL;

STATIC
VOID
EFIAPI
UggFbRedrawCallback (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UINTN                          Width  = FixedPcdGet32 (PcdMipiFrameBufferWidth);
  UINTN                          Height = FixedPcdGet32 (PcdMipiFrameBufferHeight);
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL  White  = { 0xFF, 0xFF, 0xFF, 0 };

  FbFillRect (0, 600, Width, 4, &White);
  FbFillRect (360, 0, 4, Height, &White);
  FbFillRect (20, 20, 40, 40, &White);
}

/* Шрифт 8x12 (файл UggFont.c, генерируется tools/gen_font.py). */
extern CONST UINT8  mUggFontData[95][12];
extern CONST UINTN  mUggFontFirst;
extern CONST UINTN  mUggFontCount;

/*
  Собственный вывод текста: рисуем символы прямо в framebuffer, не полагаясь
  на консольный стек UEFI (ConSplitter/GraphicsConsole). Нужно потому, что
  gST->ConOut на этом устройстве возвращает успех, но ничего не рисует.
*/
STATIC
VOID
UggDrawChar (
  IN UINTN  X,
  IN UINTN  Y,
  IN UINT8  Ch
  )
{
  UINTN  Index;
  UINTN  Row;
  UINTN  Col;
  UINT8  Bits;

  if ((Ch < mUggFontFirst) || (Ch >= mUggFontFirst + mUggFontCount)) {
    Ch = '?';
  }
  if ((Ch < mUggFontFirst) || (Ch >= mUggFontFirst + mUggFontCount)) {
    return;
  }

  Index = Ch - mUggFontFirst;
  for (Row = 0; Row < 12; Row++) {
    Bits = mUggFontData[Index][Row];
    for (Col = 0; Col < 8; Col++) {
      EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Pixel;
      Pixel.Blue  = (Bits & (0x80 >> Col)) ? 0xFF : 0x00;
      Pixel.Green = Pixel.Blue;
      Pixel.Red   = Pixel.Blue;
      Pixel.Reserved = 0;
      FbPutPixel (X + Col, Y + Row, &Pixel);
    }
  }
}

STATIC
VOID
UggDrawText (
  IN UINTN        X,
  IN UINTN        Y,
  IN CONST CHAR8  *Text
  )
{
  UINTN  Pos = 0;

  while ((*Text != 0) && (Pos < 80)) {
    UggDrawChar (X + Pos * 8, Y, (UINT8)*Text);
    Text++;
    Pos++;
  }
}

/*
  Собственный EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL.

  Зачем: штатный GraphicsConsoleDxe на этом устройстве не подключается к нашему
  GOP, из-за чего gST->ConOut существует, но ничего не рисует (OutputString
  возвращает успех и молчит). Своя реализация текстового вывода делает консоль
  UEFI настоящей: BDS, Shell и загрузчики печатают через неё, а мы рисуем текст
  своим шрифтом прямо в framebuffer.
*/
#define UGG_COLS  80
#define UGG_ROWS  50
#define UGG_CHAR_W 9
#define UGG_CHAR_H 13

STATIC UINTN                           mUggCursorX = 0;
STATIC UINTN                           mUggCursorY = 0;
STATIC EFI_SIMPLE_TEXT_OUTPUT_MODE     mUggTextMode = {
  1, 0, EFI_LIGHTGRAY | EFI_BACKGROUND_BLACK, 0, 0
};

STATIC
EFI_STATUS
EFIAPI
UggTextReset (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN BOOLEAN                          ExtendedVerification
  )
{
  (VOID)ExtendedVerification;
  mUggCursorX = 0;
  mUggCursorY = 0;
  return EFI_SUCCESS;
}

STATIC
VOID
UggTextNewLine (
  VOID
  )
{
  mUggCursorX = 0;
  mUggCursorY++;
  if (mUggCursorY >= UGG_ROWS) {
    mUggCursorY = UGG_ROWS - 1;
  }
}

STATIC
EFI_STATUS
EFIAPI
UggTextOutputString (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN CHAR16                           *String
  )
{
  UINT8  Ch;

  if (String == NULL) {
    return EFI_INVALID_PARAMETER;
  }

  while (*String != 0) {
    if (*String == L'\r') {
      mUggCursorX = 0;
    } else if (*String == L'\n') {
      UggTextNewLine ();
    } else if (*String == L'\b') {
      if (mUggCursorX > 0) {
        mUggCursorX--;
      }
    } else {
      Ch = (UINT8)(*String & 0xFF);
      if (mUggCursorX >= UGG_COLS) {
        UggTextNewLine ();
      }
      UggDrawChar (24 + mUggCursorX * UGG_CHAR_W, 20 + mUggCursorY * UGG_CHAR_H, Ch);
      mUggCursorX++;
    }
    String++;
  }
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextTestString (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN CHAR16                           *String
  )
{
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextQueryMode (
  IN  EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN  UINTN                            ModeNumber,
  OUT UINTN                            *Columns,
  OUT UINTN                            *Rows
  )
{
  if (ModeNumber != 0) {
    return EFI_UNSUPPORTED;
  }
  *Columns = UGG_COLS;
  *Rows    = UGG_ROWS;
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextSetMode (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN UINTN                            ModeNumber
  )
{
  return (ModeNumber == 0) ? EFI_SUCCESS : EFI_UNSUPPORTED;
}

STATIC
EFI_STATUS
EFIAPI
UggTextSetAttribute (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN UINTN                            Attribute
  )
{
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextClearScreen (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This
  )
{
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Black = { 0x00, 0x00, 0x00, 0 };
  UINTN                          Width  = FixedPcdGet32 (PcdMipiFrameBufferWidth);
  UINTN                          Height = FixedPcdGet32 (PcdMipiFrameBufferHeight);

  FbFillRect (0, 0, Width, Height, &Black);
  mUggCursorX = 0;
  mUggCursorY = 0;
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextSetCursorPosition (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN UINTN                            Column,
  IN UINTN                            Row
  )
{
  mUggCursorX = (Column < UGG_COLS) ? Column : UGG_COLS - 1;
  mUggCursorY = (Row < UGG_ROWS) ? Row : UGG_ROWS - 1;
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggTextEnableCursor (
  IN EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  *This,
  IN BOOLEAN                          Visible
  )
{
  mUggTextMode.CursorVisible = Visible;
  return EFI_SUCCESS;
}

STATIC EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL  mUggTextOut = {
  UggTextReset,
  UggTextOutputString,
  UggTextTestString,
  UggTextQueryMode,
  UggTextSetMode,
  UggTextSetAttribute,
  UggTextClearScreen,
  UggTextSetCursorPosition,
  UggTextEnableCursor,
  &mUggTextMode
};

/*
  Проба кнопки VOL+ (TLMM GPIO 91, active low).

  Из device tree: soc/gpio_keys/vol_up -> gpios = <&tlmm 91 GPIO_ACTIVE_LOW>,
  linux,code = 115 (KEY_VOLUMEUP). Читаем уровень пина из TLMM и показываем
  цифрой на экране: 1 = нажата, 0 = отпущена. Так проверяем адрес регистра
  и полярность, прежде чем делать настоящий драйвер ввода.
*/
#define UGG_TLMM_BASE   0x01000000
#define UGG_VOLUP_GPIO  91

/*
  Настроить пин как GPIO с подтяжкой вверх. Без этого чтение уровня
  бессмысленно: LK/UEFI пин не мультиплексировали, и FUNC_SEL может указывать
  на периферию, а не на GPIO.

  QCOM TLMM (v1, msm8937): GPIO_CFG биты [2:0] = FUNC_SEL (0 = GPIO),
  биты [4:3] = PULL (0b11 = pull-up), бит [9] = OE (0 = вход).
*/



/*
  Сканер кнопок (только чтение, никаких записей в TLMM — запись в CFG
  произвольного пина может сломать систему).

  Перебираем все пины, у которых FUNC_SEL == 0 (уже GPIO), запоминаем их
  уровни и записываем, какой пин изменился. Показываем номер изменившегося
  пина и счётчик изменений: так находится реальный пин кнопки, даже если
  device tree указывает другой.
*/
STATIC
VOID
UggKeyScan (
  VOID
  )
{
  STATIC UINT8                   PrevLevel[128];
  STATIC BOOLEAN                 PrevValid = FALSE;
  STATIC UINTN                   ChangedPin = 0;
  STATIC UINTN                   ChangeCount = 0;
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Black = { 0x00, 0x00, 0x00, 0 };
  UINTN                          Pin;
  UINT32                         Cfg;
  UINT32                         Level;

  for (Pin = 0; Pin < 122; Pin++) {
    volatile UINT32  *Reg = (volatile UINT32 *)(UINTN)(UGG_TLMM_BASE + 0x1000 * (Pin + 1));

    Cfg = Reg[0];
    if ((Cfg & 0x7) != 0) {
      continue;                      /* пин занят периферией */
    }
    Level = Reg[1] & 0x1;
    if (PrevValid) {
      if ((UINT8)Level != PrevLevel[Pin]) {
        ChangedPin = Pin;
        ChangeCount++;
      }
    }
    PrevLevel[Pin] = (UINT8)Level;
  }
  PrevValid = TRUE;

  FbFillRect (500, 200, 160, 100, &Black);
  UggDrawChar (500, 200, '0' + ((ChangedPin / 100) % 10));
  UggDrawChar (520, 200, '0' + ((ChangedPin / 10) % 10));
  UggDrawChar (540, 200, '0' + (ChangedPin % 10));
  UggDrawChar (580, 200, '0' + ((ChangeCount / 100) % 10));
  UggDrawChar (600, 200, '0' + ((ChangeCount / 10) % 10));
  UggDrawChar (620, 200, '0' + (ChangeCount % 10));
}

STATIC
VOID
EFIAPI
UggKeyPollCallback (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UggKeyScan ();
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

  /*
    Экран чистый: иначе на нём останется сплэш LK под текстом консоли.
    При PcdDebugStageBands == 3 очистку НЕ делаем — это нужно для диагностики:
    тогда на экране остаются все метки, нарисованные ДО нашего драйвера.
  */
  if ((FixedPcdGet32 (PcdDebugStageBands) != 3) && (FixedPcdGet32 (PcdDebugStageBands) != 4)) {
    FbFillRect (0, 0, Width, Height, &Black);
  }

  /*
    Отладка (PcdDebugStageBands):
      1 — полоса 1200 (GOP установлен) / 1100 (ошибка установки)
      2 — «один крест»: одна горизонтальная линия на 600-й строке и одна
          вертикальная на 360-м столбце + маркер в левом верхнем углу.
          Если на экране линий БОЛЬШЕ одной — панель читает буфер с другим
          шагом строки/смещением (рассогласование геометрии).
  */
  if (FixedPcdGet32 (PcdDebugStageBands) == 2) {
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL White = { 0xFF, 0xFF, 0xFF, 0 };

    FbFillRect (0, 600, Width, 4, &White);        /* горизонтальная линия */
    FbFillRect (360, 0, 4, Height, &White);       /* вертикальная линия */
    FbFillRect (20, 20, 40, 40, &White);          /* маркер «начало координат» */
  }

  Status = gBS->InstallMultipleProtocolInterfaces (
                  &Handle,
                  &gEfiGraphicsOutputProtocolGuid,
                  &mUggFb.Gop,
                  &gEfiSimpleTextOutProtocolGuid,
                  &mUggTextOut,
                  &gEfiDevicePathProtocolGuid,
                  (EFI_DEVICE_PATH_PROTOCOL *)mFbDevicePath,
                  NULL
                  );
  /*
    Метки: 1200 — GOP установлен; 1100 — установка НЕ удалась.
    Убрать вместе с PcdDebugStageBands, когда UEFI заработает.
  */
  if (FixedPcdGet32 (PcdDebugStageBands) != 0) {
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL  White = { 0xFF, 0xFF, 0xFF, 0 };

    if (EFI_ERROR (Status)) {
      FbFillRect (0, 1100, Width, 40, &White);
    } else {
      FbFillRect (0, 1200, Width, 40, &White);
    }
  }

  /*
    Режим 4: проверка GOP.Blt — консоль рисует текст именно через него,
    а прямая заливка (наш «крест») этот путь не проверяет.
    Рисуем через Blt белый квадрат 100x100 в (200,300) из буфера пикселей.
    Если квадрат виден — Blt работает, и текст консоли обязан быть виден.
    Если вместо белого квадрата появился красный в левом верхнем углу —
    Blt вернул ошибку.
  */
  if (FixedPcdGet32 (PcdDebugStageBands) == 4) {
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL  *Buf;
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL  WhitePixel = { 0xFF, 0xFF, 0xFF, 0 };
    EFI_STATUS                     BltStatus;
    UINTN                          I;

    Buf = AllocatePool (100 * 100 * sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL));
    if (Buf != NULL) {
      for (I = 0; I < 100 * 100; I++) {
        Buf[I] = WhitePixel;
      }
      BltStatus = mUggFb.Gop.Blt (
                    &mUggFb.Gop,
                    Buf,
                    EfiBltBufferToVideo,
                    0, 0,
                    200, 300,
                    100, 100,
                    0
                    );
      FreePool (Buf);
      if (EFI_ERROR (BltStatus)) {
        EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Red = { 0x00, 0x00, 0xFF, 0 };

        FbFillRect (0, 0, 100, 100, &Red);
      }
    }

    /*
      Проверка консольного стека БЕЗ участия BDS: подключаем контроллер к
      нашему GOP-хэндлу (это запускает GraphicsConsoleDxe/ConSplitter) и
      печатаем строку через gST->ConOut. Если строка видна — консоль
      работает, и дальше можно строить свой минимальный UI, не завися от BDS.
    */
    if (gST->ConOut != NULL) {
      gST->ConOut->OutputString (gST->ConOut, L"UGG-FB-CONSOLE-OK\r\n");
      gST->ConOut->OutputString (gST->ConOut, L"second line\r\n");
    }

    /*
      Собственный вывод текста — не зависит от консольного стека.
      Если эти строки видны, значит у нас есть рабочий вывод на экран,
      и дальше можно строить меню/диагностику сами, без GraphicsConsole.
    */
    UggDrawText (24, 120, "UGG UEFI framebuffer");
    UggDrawText (24, 140, "own text output: OK");
    UggDrawText (24, 160, "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ");
    UggDrawText (24, 180, "abcdefghijklmnopqrstuvwxyz .,:;!?-_/\\()[]{}");
  }

  ASSERT_EFI_ERROR (Status);

  /*
    Подключаем контроллер к нашему хэндлу. Именно это заставляет
    ConPlatform/ConSplitter подхватить наш SimpleTextOut: без этого
    gST->ConOut остаётся пустой консолью, OutputString возвращает успех,
    а на экране ничего не появляется.
  */
  gBS->ConnectController (Handle, NULL, NULL, TRUE);

  /* Заголовок — признак того, что драйвер дисплея и текстовый вывод живы. */
  UggDrawText (16, 4, "Ugg UEFI  MSM8940  Redmi Note 5A Prime");

  if ((FixedPcdGet32 (PcdDebugStageBands) == 2) || (FixedPcdGet32 (PcdDebugStageBands) == 5)) {
    Status = gBS->CreateEvent (
                    EVT_TIMER | EVT_NOTIFY_SIGNAL,
                    TPL_CALLBACK,
                    ((FixedPcdGet32 (PcdDebugStageBands) == 5) ? UggKeyPollCallback : (EFI_EVENT_NOTIFY)UggFbRedrawCallback),
                    NULL,
                    &mRedrawTimer
                    );
    if (!EFI_ERROR (Status)) {
      gBS->SetTimer (mRedrawTimer, TimerPeriodic, 200000);   /* 0.5 c */
    }
  }

  return Status;
}
