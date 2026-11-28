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

/*
  Проба контроллера eMMC (SDCC1).

  LK только что грузился с этой eMMC, поэтому клоки SDCC1 включены и читать
  регистры безопасно. SDCC у Qualcomm совместим с SDHCI:
    0x040 — CAPABILITIES
    0x0FE — HOST_VERSION
    0x024 — PRESENT_STATE
    0x020 — CLOCK_CONTROL
  Печатаем их текстом: по значениям видно, отвечает ли контроллер и какие
  режимы поддерживает (нужно для будущего драйвера eMMC).
*/
#define UGG_SDCC1_BASE  0x07824900

STATIC
VOID
UggHex (
  IN UINTN   X,
  IN UINTN   Y,
  IN UINT32  Value
  )
{
  STATIC CONST CHAR8  Hex[] = "0123456789ABCDEF";
  UINTN               I;

  for (I = 0; I < 8; I++) {
    UggDrawChar (X + I * 8, Y, Hex[(Value >> ((7 - I) * 4)) & 0xF]);
  }
}

STATIC
VOID
UggProbeSdcc (
  VOID
  )
{
  UggDrawText (16, 300, "SDCC1 capabilities:");
  UggHex (192, 300, *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + 0x040));
  UggDrawText (16, 320, "SDCC1 version:");
  UggHex (128, 320, *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + 0x0FE));
  UggDrawText (16, 340, "SDCC1 present state:");
  UggHex (176, 340, *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + 0x024));
  UggDrawText (16, 360, "SDCC1 clock control:");
  UggHex (176, 360, *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + 0x020));
}

/*
  Инициализация SDCC1 (eMMC) по SDHCI — первый настоящий шаг драйвера eMMC.

  Раскладка SDHCI (спецификация SD Host Controller 3.0), а не то, что я читал
  раньше: CLOCK_CONTROL_OFFSET = 0x2C (0x20 — это buffer data port), POWER
  Control = 0x29, Software Reset = 0x2F, Normal Int Status = 0x30.

  Все ожидания ограничены по числу итераций: бесконечных циклов быть не должно,
  иначе срабатывает watchdog и телефон перезагружается.

    1. печать CLOCK_CONTROL и POWER_CONTROL (как есть после LK);
    2. software reset ALL;
    3. питание шины 3.3V;
    4. включение внутреннего клока + SD-клока с делителем;
    5. CMD0 (GO_IDLE_STATE) и ожидание command complete.
*/
#define SDHCI_CLOCK_CONTROL   0x2C
#define SDHCI_POWER_CONTROL   0x29
#define SDHCI_SW_RESET        0x2F
#define SDHCI_NORMAL_INT_STAT 0x30
#define SDHCI_ERROR_INT_STAT  0x32
#define SDHCI_ARGUMENT        0x08
#define SDHCI_COMMAND         0x0E
#define SDHCI_PRESENT_STATE   0x24

STATIC
UINT32
UggSdccRd (
  IN UINTN  Off
  )
{
  return *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + Off);
}

STATIC
VOID
UggSdccWr (
  IN UINTN   Off,
  IN UINT32  Value
  )
{
  *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + Off) = Value;
}

STATIC
UINT16
UggSdccRd16 (
  IN UINTN  Off
  )
{
  return *(volatile UINT16 *)(UINTN)(UGG_SDCC1_BASE + Off);
}

STATIC
VOID
UggSdccWr16 (
  IN UINTN   Off,
  IN UINT16  Value
  )
{
  *(volatile UINT16 *)(UINTN)(UGG_SDCC1_BASE + Off) = Value;
}

STATIC
VOID
UggPrintHex (
  IN UINTN   Y,
  IN CONST CHAR8  *Label,
  IN UINT32  Value
  )
{
  UggDrawText (16, Y, Label);
  UggHex (200, Y, Value);
}

STATIC
VOID
UggSdccInit (
  VOID
  )
{
  UINT32  Reg;
  UINTN   I;

  UggPrintHex (300, "clock control:", UggSdccRd (SDHCI_CLOCK_CONTROL));
  UggPrintHex (320, "power control:", UggSdccRd (SDHCI_POWER_CONTROL));
  UggPrintHex (340, "present state:", UggSdccRd (SDHCI_PRESENT_STATE));

  /* 1) software reset ALL */
  UggSdccWr16 (SDHCI_SW_RESET, 0x1);
  for (I = 0; I < 20000; I++) {
    if ((UggSdccRd16 (SDHCI_SW_RESET) & 0x1) == 0) {
      break;
    }
  }
  UggDrawText (16, 360, (I < 20000) ? "reset: OK" : "reset: TIMEOUT");

  /* 2) питание шины 3.3V (SD_BUS_POWER=1, 3.3V = 0b111) */
  UggSdccWr16 (SDHCI_POWER_CONTROL, 0x0F);
  for (I = 0; I < 20000; I++) {
    if ((UggSdccRd16 (SDHCI_POWER_CONTROL) & 0x01) != 0) {
      break;
    }
  }
  UggDrawText (16, 380, (I < 20000) ? "power: OK" : "power: TIMEOUT");

  /* 3) внутренний клок: enable -> ждём stable -> включаем SD clock */
  UggSdccWr16 (SDHCI_CLOCK_CONTROL, 0x0001);
  for (I = 0; I < 20000; I++) {
    Reg = UggSdccRd16 (SDHCI_CLOCK_CONTROL) & 0x0002;
    if (Reg != 0) {
      break;
    }
  }
  if (I >= 20000) {
    UggDrawText (16, 400, "int clock: TIMEOUT");
  } else {
    UggDrawText (16, 400, "int clock: OK");
    /* делитель по умолчанию (база/2) + SD clock enable */
    UggSdccWr16 (SDHCI_CLOCK_CONTROL, 0x0007);
    UggPrintHex (420, "clock now:", UggSdccRd (SDHCI_CLOCK_CONTROL));
  }

  /* 4) CMD0 — карта должна ответить "command complete" */
  UggSdccWr (SDHCI_ARGUMENT, 0);
  UggSdccWr16 (SDHCI_NORMAL_INT_STAT, 0xFFFF);      /* сбросить статусы */
  UggSdccWr16 (SDHCI_ERROR_INT_STAT, 0xFFFF);
  UggSdccWr16 (SDHCI_COMMAND, 0x0000);              /* CMD0, без ответа */
  for (I = 0; I < 20000; I++) {
    Reg = UggSdccRd16 (SDHCI_NORMAL_INT_STAT);
    if ((Reg & 0x0001) != 0) {
      break;
    }
  }
  UggDrawText (16, 440, (I < 20000) ? "CMD0: OK" : "CMD0: TIMEOUT");
  UggPrintHex (460, "int status:", UggSdccRd (SDHCI_NORMAL_INT_STAT));
  UggPrintHex (480, "err status:", UggSdccRd (SDHCI_ERROR_INT_STAT));
}

/*
  Дамп вендорских регистров SDCC (0x100..0x13C).

  QCOM SDCC поверх SDHCI имеет собственный блок: режим (SDHCI / SDCC),
  настройки DLL, задержки сэмплинга, выбор 1.8/3.3 В. Пока эти регистры не
  настроены как ждёт наш SoC, команды не исполняются: CMD0 завершается
  «тишиной» (нет ни complete, ни error). Печатаем дамп, чтобы понять режим.
*/
STATIC
VOID
UggSdccDump (
  IN UINTN  Base
  )
{
  UINTN   Row;
  UINTN   Col;
  UINT32  Val;
  UINTN   Y = Base;

  for (Row = 0; Row < 16; Row++) {
    UggDrawText (16, Y, "100:");
    for (Col = 0; Col < 4; Col++) {
      Val = *(volatile UINT32 *)(UINTN)(UGG_SDCC1_BASE + 0x100 + Row * 0x10 + Col * 4);
      UggHex (64 + Col * 72, Y, Val);
    }
    Y += 20;
  }
}

/*
  Правильная инициализация SDCC1 для eMMC (по последовательности LK/lk2nd).

  У контроллера ДВЕ базы:
    hc_mem   = 0x07824900 — SDHCI-регистры (0x00..0x1FF)
    core_mem = 0x07824000 — вендорские MCI-регистры:
                           0x050 MCI_VERSION
                           0x078 MCI_HC_MODE: бит0 = SDHCI mode,
                                 бит13 = FF_CLK_SW_RST_DIS

  Без включения SDHCI-режима (core_mem+0x78 бит0) команды не исполняются:
  именно это мы наблюдали — CMD0 «тишина», статусы нулевые.

  Порядок (как в LK):
    1. HC_MODE: SDHCI mode = 1, FF_CLK_SW_RST_DIS = 1
    2. VENDOR_SPECIFIC_FUNC (hc+0x10C) = 0xA1C
    3. SDHCI software reset ALL
    4. power control = 3.3 V
    5. clock: внутренний клок -> stable -> SD clock
    6. CMD0 (GO_IDLE_STATE), затем CMD1 (SEND_OP_COND, OCR)
*/
#define UGG_SDCC_CORE   0x07824000
#define UGG_SDCC_HC     0x07824900

STATIC
UINT32
UggMciRd (
  IN UINTN  Off
  )
{
  return *(volatile UINT32 *)(UINTN)(UGG_SDCC_CORE + Off);
}

STATIC
VOID
UggMciWr (
  IN UINTN   Off,
  IN UINT32  Value
  )
{
  *(volatile UINT32 *)(UINTN)(UGG_SDCC_CORE + Off) = Value;
}

STATIC
UINT16
UggHcRd16 (
  IN UINTN  Off
  )
{
  return *(volatile UINT16 *)(UINTN)(UGG_SDCC_HC + Off);
}

STATIC
VOID
UggHcWr16 (
  IN UINTN   Off,
  IN UINT16  Value
  )
{
  *(volatile UINT16 *)(UINTN)(UGG_SDCC_HC + Off) = Value;
}

STATIC
VOID
UggHcWr (
  IN UINTN   Off,
  IN UINT32  Value
  )
{
  *(volatile UINT32 *)(UINTN)(UGG_SDCC_HC + Off) = Value;
}

STATIC
UINT32
UggHcRd (
  IN UINTN  Off
  )
{
  return *(volatile UINT32 *)(UINTN)(UGG_SDCC_HC + Off);
}

STATIC
CHAR8 *
UggYesNo (
  IN BOOLEAN  Ok
  )
{
  return Ok ? "OK" : "TIMEOUT";
}

/* Отправить команду и подождать command complete. Возвращает TRUE при успехе. */
STATIC
BOOLEAN
UggSdCmd (
  IN UINT16  CmdReg
  )
{
  UINTN   I;
  UINT16  IntStat;

  UggHcWr16 (0x30, 0xFFFF);      /* очистить normal int */
  UggHcWr16 (0x32, 0xFFFF);      /* очистить error int */
  UggHcWr16 (0x0E, CmdReg);      /* COMMAND */

  for (I = 0; I < 50000; I++) {
    IntStat = UggHcRd16 (0x30);
    if ((IntStat & 0x8000) != 0) {       /* ERROR_INTERRUPT */
      return FALSE;
    }
    if ((IntStat & 0x0001) != 0) {       /* COMMAND_COMPLETE */
      return TRUE;
    }
  }
  return FALSE;
}

STATIC
VOID
UggSdccInit2 (
  VOID
  )
{
  UINT32   Reg;
  UINTN    I;
  BOOLEAN  Ok;

  UggPrintHex (300, "MCI version:", UggMciRd (0x050));
  UggPrintHex (320, "MCI hc mode:", UggMciRd (0x078));

  /* 1) включить SDHCI-режим (бит0) и запретить сброс клока (бит13) */
  Reg  = UggMciRd (0x078);
  Reg |= (1u << 0) | (1u << 13);
  UggMciWr (0x078, Reg);
  UggPrintHex (340, "hc mode now:", UggMciRd (0x078));

  /* 2) вендорский конфиг, как у LK */
  UggHcWr (0x10C, 0xA1C);

  /* 3) software reset ALL и ожидание (не более ~100 мс) */
  UggHcWr16 (0x2F, 0x1);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2F) & 0x1) == 0) {
      break;
    }
  }
  Ok = (I < 20000);
  UggDrawText (16, 360, "sdhci reset:");
  UggDrawText (128, 360, UggYesNo (Ok));

  /* 4) питание шины 3.3 В */
  UggHcWr16 (0x29, 0x0F);

  /* 5) клок: внутренний -> stable -> SD clock (делитель /2) */
  UggHcWr16 (0x2C, 0x0001);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2C) & 0x0002) != 0) {
      break;
    }
  }
  Ok = (I < 20000);
  UggDrawText (16, 380, "int clock:");
  UggDrawText (112, 380, UggYesNo (Ok));
  UggHcWr16 (0x2C, 0x0007);
  UggPrintHex (400, "clock ctl:", UggHcRd16 (0x2C));

  /* 6) CMD0 */
  UggHcWr (0x08, 0);
  Ok = UggSdCmd (0x0000);
  UggDrawText (16, 420, "CMD0:");
  UggDrawText (80, 420, UggYesNo (Ok));
  UggPrintHex (440, "int status:", UggHcRd (0x30));

  /* 7) CMD1: SEND_OP_COND, ответ R3 (48 бит), OCR в аргументе */
  UggHcWr (0x08, 0x40FF8080);
  Ok = UggSdCmd (0x0102);
  UggDrawText (16, 460, "CMD1:");
  UggDrawText (80, 460, UggYesNo (Ok));
  UggPrintHex (480, "OCR:", UggHcRd (0x10));
  UggPrintHex (500, "err status:", UggHcRd (0x32));
}

/*
  Полная инициализация SDCC1 с обработкой питания (как в LK/WOA-драйвере).

  Добавлено то, чего не хватало: после подачи питания на шину контроллер
  выставляет BUS_ON в регистре PWRCTL_STATUS (core_mem + 0x0DC) и только
  после этого исполняет команды. LK ждёт при этом прерывание; у нас
  прерываний нет, поэтому просто опрашиваем статус.

  Регистры питания (смещения внутри core_mem), взяты из платформенных PCD
  драйвера WOA (Lumia950XLPkg, Shared.dsc.inc):
    MCI_HC_MODE     0x078  (бит0 = SDHCI mode, бит13 = FF_CLK_SW_RST_DIS)
    PWRCTL_STATUS   0x0DC  (бит0 = BUS_ON)
    PWRCTL_MASK     0x0E0
    PWRCTL_CLEAR    0x0E4
    PWRCTL_CTL      0x0E8
*/
#define UGG_MCI_HC_MODE    0x078
#define UGG_PWRCTL_STATUS  0x0DC
#define UGG_PWRCTL_MASK    0x0E0
#define UGG_PWRCTL_CLEAR   0x0E4
#define UGG_PWRCTL_CTL     0x0E8

STATIC
VOID
UggSdccInit3 (
  VOID
  )
{
  UINT32   Reg;
  UINTN    I;
  BOOLEAN  Ok;

  /* 1) SDHCI-режим + запрет сброса клока */
  Reg  = UggMciRd (UGG_MCI_HC_MODE);
  Reg |= (1u << 0) | (1u << 13);
  UggMciWr (UGG_MCI_HC_MODE, Reg);

  /* 2) вендорский конфиг + разрешить прерывания питания в маске */
  UggHcWr (0x10C, 0xA1C);
  UggMciWr (UGG_PWRCTL_MASK, 0xF);

  /* 3) сброс SDHCI */
  UggHcWr16 (0x2F, 0x1);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2F) & 0x1) == 0) {
      break;
    }
  }
  UggDrawText (16, 300, "reset:");
  UggDrawText (72, 300, UggYesNo (I < 20000));

  /* 4) клок: внутренний -> stable -> SD clock */
  UggHcWr16 (0x2C, 0x0001);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2C) & 0x0002) != 0) {
      break;
    }
  }
  UggDrawText (16, 320, "int clock:");
  UggDrawText (112, 320, UggYesNo (I < 20000));
  UggHcWr16 (0x2C, 0x0007);

  /* 5) питание шины 3.3 В и ОЖИДАНИЕ BUS_ON в PWRCTL_STATUS */
  UggMciWr (UGG_PWRCTL_CLEAR, 0xF);      /* сбросить старые статусы */
  UggHcWr16 (0x29, 0x0F);                /* SD bus power on, 3.3 В */
  for (I = 0; I < 200000; I++) {
    Reg = UggMciRd (UGG_PWRCTL_STATUS);
    if ((Reg & 0x1) != 0) {              /* BUS_ON */
      break;
    }
  }
  Ok = (I < 200000);
  UggDrawText (16, 340, "bus power:");
  UggDrawText (112, 340, UggYesNo (Ok));
  UggPrintHex (360, "pwrctl status:", UggMciRd (UGG_PWRCTL_STATUS));
  UggMciWr (UGG_PWRCTL_CLEAR, 0xF);      /* подтвердить */
  UggPrintHex (380, "pwrctl ctl:", UggMciRd (UGG_PWRCTL_CTL));

  /* 6) CMD0 */
  UggHcWr (0x08, 0);
  Ok = UggSdCmd (0x0000);
  UggDrawText (16, 400, "CMD0:");
  UggDrawText (80, 400, UggYesNo (Ok));
  UggPrintHex (420, "int status:", UggHcRd (0x30));

  /* 7) CMD1 — SEND_OP_COND, OCR */
  UggHcWr (0x08, 0x40FF8080);
  Ok = UggSdCmd (0x0102);
  UggDrawText (16, 440, "CMD1:");
  UggDrawText (80, 440, UggYesNo (Ok));
  UggPrintHex (460, "OCR:", UggHcRd (0x10));
  UggPrintHex (480, "err status:", UggHcRd (0x32));
}

/*
  Питание eMMC по способу LK (легаси-режим MCI).

  LK на msm8937 НЕ использует SDHCI-режим: он специально выключает его
  (`MCI_HC_MODE` бит0 = 0) и работает через легаси-регистры MCI, а питание
  включает записью в `MCI_POWER` (core_mem + 0x0):
      MMC_BOOT_MCI_PWR_ON | MMC_BOOT_MCI_PWR_UP = 0x03

  Мы наблюдали `PWRCTL_STATUS = BUS_OFF`, потому что питания не запрашивали
  этим способом. Проба ниже включает питание и проверяет статус, затем
  дополнительно пробует SDHCI-путь.
*/
#define UGG_MCI_POWER  0x000

STATIC
VOID
UggSdccPowerProbe (
  VOID
  )
{
  UINTN   I;
  UINT32  Reg;

  UggPrintHex (300, "pwrctl before:", UggMciRd (UGG_PWRCTL_STATUS));

  /* 1) легаси-режим: выключить SDHCI (как LK) */
  Reg  = UggMciRd (UGG_MCI_HC_MODE);
  Reg &= ~(1u << 0);
  UggMciWr (UGG_MCI_HC_MODE, Reg);

  /* 2) сброс контроллера битом CORE_SW_RST (MCI_POWER бит 7) */
  *(volatile UINT8 *)(UINTN)(UGG_SDCC_CORE + UGG_MCI_POWER) = (UINT8)(1u << 7);

  /* 3) питание: PWR_ON | PWR_UP = 0x03 */
  *(volatile UINT8 *)(UINTN)(UGG_SDCC_CORE + UGG_MCI_POWER) = 0x03;

  /* 4) ждём BUS_ON в статусе питания */
  for (I = 0; I < 200000; I++) {
    Reg = UggMciRd (UGG_PWRCTL_STATUS);
    if ((Reg & 0x1) != 0) {
      break;
    }
  }
  UggDrawText (16, 320, "legacy power:");
  UggDrawText (128, 320, UggYesNo (I < 200000));
  UggPrintHex (340, "pwrctl after:", UggMciRd (UGG_PWRCTL_STATUS));
  UggPrintHex (360, "mci power:", *(volatile UINT8 *)(UINTN)(UGG_SDCC_CORE + UGG_MCI_POWER));

  /* 5) теперь SDHCI: включить режим, клок, питание и попробовать CMD0 */
  Reg  = UggMciRd (UGG_MCI_HC_MODE);
  Reg |= (1u << 0) | (1u << 13);
  UggMciWr (UGG_MCI_HC_MODE, Reg);
  UggHcWr (0x10C, 0xA1C);

  UggHcWr16 (0x2F, 0x1);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2F) & 0x1) == 0) {
      break;
    }
  }
  UggHcWr16 (0x2C, 0x0001);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2C) & 0x0002) != 0) {
      break;
    }
  }
  UggHcWr16 (0x2C, 0x0007);
  UggHcWr16 (0x29, 0x0F);

  UggHcWr (0x08, 0);
  Reg = UggSdCmd (0x0000);
  UggDrawText (16, 380, "CMD0 after power:");
  UggDrawText (192, 380, UggYesNo (Reg != 0));
  UggPrintHex (400, "int status:", UggHcRd (0x30));
  UggPrintHex (420, "pwrctl final:", UggMciRd (UGG_PWRCTL_STATUS));
}

/*
  Настройка клока SDCC1 через GCC для msm8937.

  Смещения взяты из стокового драйвера клоков Xiaomi (ветка land-m-oss,
  файл drivers/clk/msm/clock-gcc-8936.c — msm8937 входит в это семейство):

    GCC base                0x01800000
    SDCC1_APPS_CMD_RCGR     0x42004   (+0x4 CFG, +0x8 M, +0xC N, +0x10 D)
    SDCC1_APPS_CBCR         0x42018   (бит0 = enable ветки)

  Биты (clock-local2.c):
    CMD: бит1 = ROOT_ENABLE, бит31 = ROOT_STATUS (клок «пошёл»)
    CFG: DIV[4:0], SRC_SEL[10:8], MND_MODE[13:12] (0x2 = dual edge для MND)

  Частота = parent * N / (M * D). Для 400 кГц от XO (19.2 МГц): m=12, n=1, d=4.

  Источник (SRC_SEL) подбираем сами: перебираем 0..7 и оставляем тот, при
  котором ROOT_STATUS становится 1 — так не нужно угадывать нумерацию
  источников в конкретном SoC.
*/
#define UGG_GCC_BASE            0x01800000
#define UGG_GCC_SDCC1_CMD_RCGR  0x42004
#define UGG_GCC_SDCC1_CBCR      0x42018

STATIC
UINT32
UggGccRd (
  IN UINTN  Off
  )
{
  return *(volatile UINT32 *)(UINTN)(UGG_GCC_BASE + Off);
}

STATIC
VOID
UggGccWr (
  IN UINTN   Off,
  IN UINT32  Value
  )
{
  *(volatile UINT32 *)(UINTN)(UGG_GCC_BASE + Off) = Value;
}

/* Настроить SDCC1 apps clock на 400 кГц и включить ветку. TRUE — удалось. */
STATIC
BOOLEAN
UggSdccClockInit (
  VOID
  )
{
  UINTN   Src;
  UINTN   I;
  UINT32  Cmd;
  BOOLEAN  Ok = FALSE;

  for (Src = 0; Src < 8; Src++) {
    /* M=12, N=1, D=4  ->  400 кГц от XO */
    UggGccWr (UGG_GCC_SDCC1_CMD_RCGR + 0x8, 12);
    UggGccWr (UGG_GCC_SDCC1_CMD_RCGR + 0xC, 1);
    UggGccWr (UGG_GCC_SDCC1_CMD_RCGR + 0x10, 4);

    /* CFG: SRC_SEL = Src, DIV = 0, MND dual-edge mode */
    UggGccWr (
      UGG_GCC_SDCC1_CMD_RCGR + 0x4,
      (UINT32)((0x2u << 12) | ((Src & 0x7u) << 8))
      );

    /* ROOT_ENABLE */
    Cmd  = UggGccRd (UGG_GCC_SDCC1_CMD_RCGR);
    Cmd |= (1u << 1);
    UggGccWr (UGG_GCC_SDCC1_CMD_RCGR, Cmd);

    /* ждём ROOT_STATUS (бит 31) */
    for (I = 0; I < 20000; I++) {
      if ((UggGccRd (UGG_GCC_SDCC1_CMD_RCGR) & (1u << 31)) != 0) {
        Ok = TRUE;
        break;
      }
    }
    if (Ok) {
      break;
    }
  }

  /* включить ветку SDCC1 apps (бит 0) */
  if (Ok) {
    UggGccWr (UGG_GCC_SDCC1_CBCR, UggGccRd (UGG_GCC_SDCC1_CBCR) | 0x1);
  } else {
    Src = 0xFF;
  }

  UggDrawText (16, 300, "sdcc1 clk src:");
  UggDrawChar (144, 300, (Src < 8) ? (CHAR8)('0' + Src) : 'X');
  UggDrawText (16, 320, "clk on:");
  UggDrawText (80, 320, UggYesNo (Ok));
  UggPrintHex (340, "cmd rcgr:", UggGccRd (UGG_GCC_SDCC1_CMD_RCGR));
  UggPrintHex (360, "cbr:", UggGccRd (UGG_GCC_SDCC1_CBCR));
  return Ok;
}

/*
  Правильный порядок инициализации SDCC (как в LK): reset -> ПИТАНИЕ ->
  ожидание BUS_ON -> клок -> команды.

  В предыдущих пробах мы включали клок раньше питания, поэтому контроллер
  мог не выходить из BUS_OFF. Кроме того, уточнение по драйверу клоков:
  бит 31 в CMD_RCGR — это ROOT_OFF, и `rcg_on_check` ждёт его СБРОСА.
  Значит `cmd rcgr = 0x...FF2` с битом 31 = 0 означает «клок включён».

  Ещё важное: ветка SDCC1 apps включается в CBCR (0x42018), AHB-ветка —
  0x4201C; включаем обе.
*/
STATIC
VOID
UggSdccInit4 (
  VOID
  )
{
  UINTN    I;
  UINT32   Reg;
  BOOLEAN  Ok;

  /* 0) GCC: включить AHB и apps ветки SDCC1 */
  UggGccWr (0x4201C, UggGccRd (0x4201C) | 0x1);
  UggGccWr (0x42018, UggGccRd (0x42018) | 0x1);
  UggPrintHex (300, "gcc cbr:", UggGccRd (0x42018));
  UggPrintHex (320, "gcc cmd rcgr:", UggGccRd (0x42004));

  /* 1) SDHCI mode + вендорский конфиг */
  Reg  = UggMciRd (UGG_MCI_HC_MODE);
  Reg |= (1u << 0) | (1u << 13);
  UggMciWr (UGG_MCI_HC_MODE, Reg);
  UggHcWr (0x10C, 0xA1C);
  UggMciWr (UGG_PWRCTL_MASK, 0xF);
  UggMciWr (UGG_PWRCTL_CLEAR, 0xF);

  /* 2) reset */
  UggHcWr16 (0x2F, 0x1);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2F) & 0x1) == 0) {
      break;
    }
  }
  UggDrawText (16, 340, "reset:");
  UggDrawText (64, 340, UggYesNo (I < 20000));

  /* 3) ПИТАНИЕ до клока */
  UggHcWr16 (0x29, 0x0F);
  for (I = 0; I < 200000; I++) {
    Reg = UggMciRd (UGG_PWRCTL_STATUS);
    if ((Reg & 0x1) != 0) {
      break;
    }
  }
  Ok = (I < 200000);
  UggDrawText (16, 360, "bus power:");
  UggDrawText (112, 360, UggYesNo (Ok));
  UggPrintHex (380, "pwrctl status:", UggMciRd (UGG_PWRCTL_STATUS));

  /* 4) клок после питания */
  UggHcWr16 (0x2C, 0x0001);
  for (I = 0; I < 20000; I++) {
    if ((UggHcRd16 (0x2C) & 0x0002) != 0) {
      break;
    }
  }
  UggHcWr16 (0x2C, 0x0007);
  UggDrawText (16, 400, "clock:");
  UggDrawText (64, 400, UggYesNo (I < 20000));

  /* 5) CMD0 */
  UggHcWr (0x08, 0);
  Ok = UggSdCmd (0x0000);
  UggDrawText (16, 420, "CMD0:");
  UggDrawText (80, 420, UggYesNo (Ok));
  UggPrintHex (440, "int status:", UggHcRd (0x30));
  UggPrintHex (460, "pwrctl final:", UggMciRd (UGG_PWRCTL_STATUS));
}

/*
  Минимальный SPMI-мастер (PMIC Arbiter v2) для msm8937.

  Нужен, чтобы управлять PMIC: питание eMMC (сейчас BUS_OFF) и кнопки PON.

  Адреса из device tree (arch/arm/boot/dts/qcom/msm8937.dtsi, узел
  qcom,spmi@200f000):
      core  0x0200F000 (0x1000)   — версия арбитра
      cnfg  0x0200A000 (0x2100)   — таблица PPID->канал, по смещению 0x0B00
      chnls 0x02400000 (0x800000) — окна каналов
      qcom,pmic-arb-ee = 0        — исполнительное окружение APSS

  Окно канала: chnls + 0x8000 * apid + 0x1000 * ee
    CMD     0x00   (opc<<27) | ((addr & 0xFF) << 4) | (bc & 7)
    STATUS  0x08   бит0 DONE, бит1 FAILURE, бит2 DENIED, бит3 DROPPED
    RDATA0  0x18
  opcode EXT_READ = 13, EXT_WRITE = 2.

  Таблица PPID->канал — бинарное дерево из 4-байтовых записей:
    бит[21:18] — номер бита PPID, [17] флаг «есть ветка 0», [16:9] результат 0,
    [8] флаг «есть ветка 1», [7:0] результат ветки 1.
*/
#define UGG_SPMI_CORE    0x0200F000
#define UGG_SPMI_CNFG    0x0200A000
#define UGG_SPMI_CHNLS   0x02400000
#define UGG_SPMI_EE      0
#ifndef UGG_SPMI_OBSRVR
#define UGG_SPMI_OBSRVR  0x02C00000
#endif

STATIC
UINT32
UggSpmiRd (
  IN UINTN  Addr
  )
{
  return *(volatile UINT32 *)(UINTN)Addr;
}

STATIC
VOID
UggSpmiWr (
  IN UINTN   Addr,
  IN UINT32  Value
  )
{
  *(volatile UINT32 *)(UINTN)Addr = Value;
}

/* Найти канал (apid) для пары (sid, addr>>8). FALSE — не найдено. */
STATIC
BOOLEAN
UggSpmiFindChannel (
  IN  UINT8  Sid,
  IN  UINT8  Periph,
  OUT UINT8  *Apid
  )
{
  UINT16  Ppid = (UINT16)(((UINT16)Sid << 8) | Periph);
  UINTN   Index = 0;
  UINTN   I;
  UINT32  Data;
  UINTN   Bit;
  BOOLEAN Branch;

  for (I = 0; I < 16; I++) {
    Data = UggSpmiRd (UGG_SPMI_CNFG + 0x0B00 + Index * 4);
    Bit  = (Data >> 18) & 0xF;

    Branch = ((Ppid >> Bit) & 0x1) ? (BOOLEAN)TRUE : (BOOLEAN)FALSE;

    if (Branch) {
      if ((Data >> 8) & 0x1) {
        /* есть ветка 1 -> идём дальше по дереву */
        Index = (Data >> 0) & 0xFF;
      } else {
        *Apid = (UINT8)((Data >> 0) & 0xFF);
        return TRUE;
      }
    } else {
      if ((Data >> 17) & 0x1) {
        Index = (Data >> 9) & 0xFF;
      } else {
        *Apid = (UINT8)((Data >> 9) & 0xFF);
        return TRUE;
      }
    }
  }
  return FALSE;
}

/* Прочитать байт из PMIC. Возвращает TRUE при успехе. */
STATIC
BOOLEAN
UggSpmiReadByte (
  IN  UINT8  Sid,
  IN  UINT8  Periph,
  IN  UINT8  Reg,
  OUT UINT8  *Value
  )
{
  UINT8    Apid;
  UINTN    Chan;
  UINTN    I;
  UINT32   Cmd;
  UINT32   Status;

  if (!UggSpmiFindChannel (Sid, Periph, &Apid)) {
    return FALSE;
  }

  /*
    Каналы: команда пишется в chnls, статус и данные читаются из obsrvr
    (так устроен SPMI PMIC Arbiter v2 — "wr_base" и "rd_base" в драйвере).
  */
  Chan = 0x8000 * (UINTN)Apid + 0x1000 * UGG_SPMI_EE;

  /* CMD: EXT_READ (13), адрес регистра, 1 байт */
  Cmd = (UINT32)((13u << 27) | (((UINT32)Reg & 0xFFu) << 4) | 0u);
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x00, Cmd);

  for (I = 0; I < 100000; I++) {
    Status = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x08);
    if ((Status & 0x1) != 0) {
      break;
    }
  }
  if (I >= 100000) {
    return FALSE;
  }
  if ((Status & 0x0E) != 0) {      /* FAILURE / DENIED / DROPPED */
    return FALSE;
  }

  *Value = (UINT8)(UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x18) & 0xFF);
  return TRUE;
}

STATIC
VOID
UggSpmiProbe (
  VOID
  )
{
  UINT8    Apid = 0xFF;
  UINT8    RevId = 0;
  BOOLEAN  Found;
  BOOLEAN  Ok;

  UggPrintHex (300, "spmi version:", UggSpmiRd (UGG_SPMI_CORE + 0x0000));

  Found = UggSpmiFindChannel (0, 0, &Apid);
  UggDrawText (16, 320, "ppid0 channel:");
  UggHex (176, 320, Found ? Apid : 0xFFFFFFFF);

  /* PMIC top-level: sid 0, peripheral 0, регистр 0x04 = REVID */
  Ok = UggSpmiReadByte (0, 0, 0x04, &RevId);
  UggDrawText (16, 340, "pmic revid read:");
  UggDrawText (192, 340, UggYesNo (Ok));
  UggPrintHex (360, "revid:", RevId);

  /* и ещё пару регистров для контроля */
  Ok = UggSpmiReadByte (0, 0, 0x05, &RevId);
  UggPrintHex (380, "reg5:", RevId);
}

/*
  Пошаговая проба SPMI: метка рисуется ДО обращения к очередному блоку,
  поэтому по экрану видно, на каком именно обращении устройство зависло.

  Уточнение из драйвера (spmi-pmic-arb.c, v2):
      wr_base = "chnls"  (0x02400000) — сюда пишутся CMD
      rd_base = "obsrvr" (0x02C00000) — отсюда читаются STATUS и RDATA
  Раньше мы опрашивали статус по chnls — это неверно.
*/
#define UGG_SPMI_OBSRVR  0x02C00000


STATIC
VOID
UggSpmiProbe2 (
  VOID
  )
{
  UINT32  Val;

  /* 1) только ядро арбитра */
  UggDrawText (16, 300, "1 core:");
  Val = UggSpmiRd (UGG_SPMI_CORE + 0x0000);
  UggPrintHex (300, "   val:", Val);

  /* 2) регион конфигурации (таблица mapping) */
  UggDrawText (16, 320, "2 cnfg:");
  Val = UggSpmiRd (UGG_SPMI_CNFG + 0x0B00);
  UggPrintHex (320, "   val:", Val);

  /* 3) окно каналов (chnls) */
  UggDrawText (16, 340, "3 chnls:");
  Val = UggSpmiRd (UGG_SPMI_CHNLS + 0x0000);
  UggPrintHex (340, "   val:", Val);

  /* 4) окно наблюдения (obsrvr) */
  UggDrawText (16, 360, "4 obsrvr:");
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + 0x0000);
  UggPrintHex (360, "   val:", Val);
}

/*
  Настоящая транзакция SPMI: читаем REVID у PMIC (sid 0, peripheral 0,
  регистр 0x04). Если значение правдоподобное — шина и PMIC под нашим
  контролем, и дальше можно включать регуляторы (питание eMMC) и PON (кнопки).
*/
STATIC
VOID
UggSpmiReadProbe (
  VOID
  )
{
  UINT8    Apid = 0xFF;
  UINT8    Val = 0;
  BOOLEAN  Found;
  BOOLEAN  Ok;
  UINT8    Idx;

  Found = UggSpmiFindChannel (0, 0, &Apid);
  UggDrawText (16, 300, "channel for ppid0:");
  UggHex (176, 300, Found ? Apid : 0xFFFFFFFF);

  Ok = UggSpmiReadByte (0, 0, 0x04, &Val);
  UggDrawText (16, 320, "read revid:");
  UggDrawText (128, 320, UggYesNo (Ok));
  UggPrintHex (340, "revid:", Val);

  for (Idx = 0; Idx < 8; Idx++) {
    if (UggSpmiReadByte (0, 0, Idx, &Val)) {
      UggHex (16 + Idx * 72, 360, Idx);
      UggHex (48 + Idx * 72, 360, Val);
    } else {
      UggDrawText (16 + Idx * 72, 360, "--");
    }
  }
}
/*
  Безопасный этап: только поиск канала для PPID (чтение таблицы mapping,
  никаких транзакций в каналы). Печатаем путь по дереву, чтобы проверить,
  что разбор таблицы верный, и узнать номер канала для PMIC (ppid 0).
*/
STATIC
VOID
UggSpmiLookupProbe (
  VOID
  )
{
  UINT16   Ppid = 0;
  UINTN    Index = 0;
  UINTN    Step;
  UINTN    Y = 300;
  UINT32   Data;
  UINTN    Bit;
  BOOLEAN  Branch;
  BOOLEAN  Done = FALSE;
  UINT8    Apid = 0xFF;

  UggDrawText (16, 280, "lookup ppid0, path:");

  for (Step = 0; Step < 20 && !Done; Step++) {
    Data = UggSpmiRd (UGG_SPMI_CNFG + 0x0B00 + Index * 4);
    Bit  = (Data >> 18) & 0xF;

    UggDrawText (16, Y, "idx:");
    UggHex (56, Y, Index);
    UggDrawText (120, Y, "data:");
    UggHex (168, Y, Data);
    Y += 20;

    Branch = ((Ppid >> Bit) & 0x1) ? TRUE : FALSE;
    if (Branch) {
      if ((Data >> 8) & 0x1) {
        Index = (Data >> 0) & 0xFF;
      } else {
        Apid  = (UINT8)((Data >> 0) & 0xFF);
        Done  = TRUE;
      }
    } else {
      if ((Data >> 17) & 0x1) {
        Index = (Data >> 9) & 0xFF;
      } else {
        Apid  = (UINT8)((Data >> 9) & 0xFF);
        Done  = TRUE;
      }
    }
  }

  UggDrawText (16, Y + 10, "apid:");
  UggHex (64, Y + 10, Done ? Apid : 0xFFFFFFFF);
  UggDrawText (16, Y + 30, "done:");
  UggDrawText (64, Y + 30, UggYesNo (Done));
}
/*
  Транзакция SPMI по последовательности LK (spmi.c):

    1. найти канал по PPID  (таблица дерева, сделано — apid 0x72 для PMIC top)
    2. записать CONFIG = 0 в окно канала  (ОТКЛЮЧИТЬ IRQ-режим; мы этого не
       делали, и, вероятно, поэтому команда «висела»)
    3. записать CMD (opcode << 27 | offset << 4 | byte_count-1)
    4. опросить STATUS (бит 0 = DONE) — читается из окна observer
    5. прочитать RDATA0 (тоже из observer)

  Одна попытка — чтобы при зависании не терять остальные данные.
*/
STATIC
VOID
UggSpmiXfer (
  VOID
  )
{
  UINT8    Apid = 0xFF;
  UINTN    Chan;
  UINTN    I;
  UINT32   Cmd;
  UINT32   Status;
  UINT32   Data;
  BOOLEAN  Found;

  Found = UggSpmiFindChannel (0, 0, &Apid);
  UggDrawText (16, 300, "apid:");
  UggHex (64, 300, Found ? Apid : 0xFFFFFFFF);
  if (!Found) {
    return;
  }

  Chan = 0x8000 * (UINTN)Apid + 0x1000 * UGG_SPMI_EE;

  /* 2) CONFIG = 0: режим опроса вместо прерываний */
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x04, 0);
  UggDrawText (16, 320, "config cleared");

  /* 3) CMD: EXT_READ(13), регистр 0x04, 1 байт */
  Cmd = (UINT32)((13u << 27) | ((0x04u & 0xFFu) << 4) | 0u);
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x00, Cmd);
  UggDrawText (16, 340, "cmd written");

  /* 4) STATUS из окна observer */
  Status = 0;
  for (I = 0; I < 200000; I++) {
    Status = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x08);
    if ((Status & 0x1) != 0) {
      break;
    }
  }
  UggDrawText (16, 360, "status:");
  UggHex (88, 360, Status);
  UggDrawText (16, 380, "done:");
  UggDrawText (64, 380, (Status & 0x1) ? "YES" : "NO");

  /* 5) RDATA0 */
  Data = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x18);
  UggDrawText (16, 400, "rdata:");
  UggHex (80, 400, Data);
  UggDrawText (16, 420, "pmic revid:");
  UggHex (112, 420, Data & 0xFF);
}
/*
  Безопасная проба окна канала SPMI (только чтение).

  Канал PMIC top: apid 0x72 -> смещение 0x8000 * 0x72 = 0x390000.
  Читаем по три регистра в каждом окне (CMD/CONFIG/STATUS) и в observer.
  Если чтения возвращаются — блок доступен и «вешает» именно запись CMD.
  Если чтение зависает — окно недоступно (клок/владелец), и нужен другой путь.

  Каждый шаг подписан ДО обращения, чтобы по экрану видеть, где остановились.
*/
STATIC
VOID
UggSpmiWindowProbe (
  VOID
  )
{
  UINTN   Chan = 0x8000 * 0x72;
  UINT32  Val;
  UINTN   Y = 300;

  UggDrawText (16, 280, "channel 0x72 window, read only:");

  /* окно записи (chnls) */
  UggDrawText (16, Y, "chnls+0:");
  Val = UggSpmiRd (UGG_SPMI_CHNLS + Chan + 0x00);
  UggHex (104, Y, Val);
  Y += 20;

  UggDrawText (16, Y, "chnls+4:");
  Val = UggSpmiRd (UGG_SPMI_CHNLS + Chan + 0x04);
  UggHex (104, Y, Val);
  Y += 20;

  UggDrawText (16, Y, "chnls+8:");
  Val = UggSpmiRd (UGG_SPMI_CHNLS + Chan + 0x08);
  UggHex (104, Y, Val);
  Y += 20;

  /* окно наблюдения (obsrvr) */
  UggDrawText (16, Y, "obsrv+0:");
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x00);
  UggHex (104, Y, Val);
  Y += 20;

  UggDrawText (16, Y, "obsrv+8:");
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x08);
  UggHex (104, Y, Val);
  Y += 20;

  UggDrawText (16, Y, "obsrv+18:");
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x18);
  UggHex (104, Y, Val);
  Y += 20;

  UggDrawText (16, Y + 10, "all reads returned");
}
/*
  Пошаговая проверка ЗАПИСИ в окно канала SPMI (что именно роняет систему).

  Из предыдущей пробы известно:
    chnls+0x0 = 0x080004B0  (CMD, оставшийся от LK: opcode 1 = EXT_READL,
                             offset 0x4B)
    chnls+0x4 = 0            (CONFIG, IRQ-режим уже выключен)
    chnls+0x8 = 0x1          (STATUS: DONE)

  Шаги подписаны до выполнения, поэтому по экрану видно, на какой записи
  устройство останавливается.
*/
STATIC
VOID
UggSpmiWriteProbe (
  VOID
  )
{
  UINTN   Chan = 0x8000 * 0x72;
  UINT32  Val;

  UggDrawText (16, 280, "write tests on channel 0x72:");

  /* W1: вернуть CONFIG = 0 (значение не меняется — только проверка записи) */
  UggDrawText (16, 300, "W1 config=0 ...");
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x04, 0);
  UggDrawText (16, 320, "W1 done");

  /* W2: переотправить РОВНО ту команду, что оставил LK (opcode 1, off 0x4B) */
  UggDrawText (16, 340, "W2 cmd=080004B0 ...");
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x00, 0x080004B0);
  UggDrawText (16, 360, "W2 done");

  /* статус после записи (читаем из observer) */
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x08);
  UggDrawText (16, 380, "status:");
  UggHex (88, 380, Val);

  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x18);
  UggDrawText (16, 400, "rdata:");
  UggHex (80, 400, Val);

  /* W3: наша команда с opcode 1 (EXT_READL), регистр 0x04, 1 байт */
  UggDrawText (16, 420, "W3 cmd=opcode1 off4 ...");
  UggSpmiWr (UGG_SPMI_CHNLS + Chan + 0x00, (UINT32)((1u << 27) | (0x04u << 4)));
  UggDrawText (16, 440, "W3 done");

  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x08);
  UggDrawText (16, 460, "status2:");
  UggHex (96, 460, Val);
  Val = UggSpmiRd (UGG_SPMI_OBSRVR + Chan + 0x18);
  UggDrawText (16, 480, "rdata2:");
  UggHex (96, 480, Val);
  UggDrawText (16, 500, "revid:");
  UggHex (72, 500, Val & 0xFF);
}
/*
  Сверка адресации SPMI (только чтение).

  1) Таблица REG_CHNL (core + 0x800 + 4*i): каждая запись кодирует
     slave_id в битах [19:16] и pid в [15:8] для канала i. Если запись для
     i = 0x72 содержит sid=0, pid=0 — канал PMIC top найден верно.
  2) Сравниваем значения по адресу LK (core + 0xF800 + chnl*0x80) и по
     адресу Linux v2 (chnls + 0x8000*chnl). Где лежит "настоящий" CMD —
     там значения будут разными для разных каналов.
*/
STATIC
VOID
UggSpmiAddrProbe (
  VOID
  )
{
  UINTN   I;
  UINT32  Val;
  UINTN   Y = 300;

  UggDrawText (16, 280, "reg_chnl table (sid/pid per channel):");
  for (I = 0; I < 4; I++) {
    /* смотрим каналы 0x70..0x73 */
    Val = UggSpmiRd (UGG_SPMI_CORE + 0x800 + 4 * (0x70 + I));
    UggDrawText (16, Y, "ch:");
    UggHex (48, Y, 0x70 + I);
    UggDrawText (112, Y, "sid/pid:");
    UggHex (176, Y, Val);
    Y += 20;
  }

  Y += 10;
  UggDrawText (16, Y, "LK-style cmd addr:");
  UggHex (168, Y, UggSpmiRd (UGG_SPMI_CORE + 0xF800 + 0x72 * 0x80));
  Y += 20;
  UggDrawText (16, Y, "LK-style status addr:");
  UggHex (184, Y, UggSpmiRd (UGG_SPMI_CORE + 0xF808 + 0x72 * 0x80));
  Y += 20;
  UggDrawText (16, Y, "v2 chnls cmd:");
  UggHex (128, Y, UggSpmiRd (UGG_SPMI_CHNLS + 0x8000 * 0x72 + 0x00));
  Y += 20;
  UggDrawText (16, Y, "v2 chnls status:");
  UggHex (144, Y, UggSpmiRd (UGG_SPMI_CHNLS + 0x8000 * 0x72 + 0x08));
  Y += 20;
  UggDrawText (16, Y, "v2 chan 0x71 cmd:");
  UggHex (152, Y, UggSpmiRd (UGG_SPMI_CHNLS + 0x8000 * 0x71 + 0x00));
  Y += 20;
  UggDrawText (16, Y, "v2 chan 0x73 cmd:");
  UggHex (152, Y, UggSpmiRd (UGG_SPMI_CHNLS + 0x8000 * 0x73 + 0x00));
}
/*
  Чтение уровней TLMM для узкого диапазона пинов (80..100) — БЕЗ записей
  в CFG (запись ранее роняла систему). Нужно найти реальный пин кнопки VOL+:
  в device tree указан GPIO 91, но он не реагирует.

  На экран выводится:
    - по одному значению на пин: 0/1 (уровень входа);
    - номер пина, который изменился последним;
    - счётчик изменений.

  Опрос идёт по таймеру (150 мс), поэтому нажатие видно почти сразу.
*/
#define UGG_SCAN_FIRST 80
#define UGG_SCAN_LAST  100

STATIC UINT8   mPinPrev[UGG_SCAN_LAST - UGG_SCAN_FIRST + 1];
STATIC UINT8   mPinNow[UGG_SCAN_LAST - UGG_SCAN_FIRST + 1];
STATIC BOOLEAN mPinInit = FALSE;
STATIC UINTN   mPinChanged = 0xFFFF;
STATIC UINTN   mPinChanges = 0;

STATIC
VOID
UggPinScan (
  VOID
  )
{
  UINTN   Pin;
  UINTN   Idx;
  UINT32  Cfg;
  UINT32  Level;
  UINT8   Digits[UGG_SCAN_LAST - UGG_SCAN_FIRST + 1];

  for (Pin = UGG_SCAN_FIRST; Pin <= UGG_SCAN_LAST; Pin++) {
    Cfg   = *(volatile UINT32 *)(UINTN)(UGG_TLMM_BASE + 0x1000 * (Pin + 1));
    Level = *(volatile UINT32 *)(UINTN)(UGG_TLMM_BASE + 0x1000 * (Pin + 1) + 4) & 1;
    Idx = Pin - UGG_SCAN_FIRST;
    Digits[Idx] = (UINT8)Level;
    if (mPinInit && (Level != mPinPrev[Idx])) {
      mPinChanged = Pin;
      mPinChanges++;
    }
    mPinPrev[Idx] = (UINT8)Level;
    (VOID)Cfg;
  }
  mPinInit = TRUE;

  /* уровни: 21 значение, по 3 символа */
  for (Idx = 0; Idx <= (UINTN)(UGG_SCAN_LAST - UGG_SCAN_FIRST); Idx++) {
    UggDrawChar (16 + Idx * 28, 300, (CHAR8)('0' + Digits[Idx]));
    UggDrawChar (16 + Idx * 28, 330, (CHAR8)('0' + ((UGG_SCAN_FIRST + Idx) / 10) % 10));
    UggDrawChar (16 + Idx * 28, 350, (CHAR8)('0' + (UGG_SCAN_FIRST + Idx) % 10));
  }

  UggDrawText (16, 400, "changed pin:");
  if (mPinChanged == 0xFFFF) {
    UggDrawText (144, 400, "none");
  } else {
    UggDrawChar (144, 400, (CHAR8)('0' + (mPinChanged / 100) % 10));
    UggDrawChar (164, 400, (CHAR8)('0' + (mPinChanged / 10) % 10));
    UggDrawChar (184, 400, (CHAR8)('0' + mPinChanged % 10));
  }
  UggDrawText (16, 420, "changes:");
  UggDrawChar (104, 420, (CHAR8)('0' + (mPinChanges / 100) % 10));
  UggDrawChar (124, 420, (CHAR8)('0' + (mPinChanges / 10) % 10));
  UggDrawChar (144, 420, (CHAR8)('0' + mPinChanges % 10));
}

STATIC
VOID
EFIAPI
UggPinScanCallback (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UggPinScan ();
}
/*
  Одиночное чтение уровней TLMM (без таймера) — изоляция причины сброса.
  Читаем 5 пинов вокруг 91 и 3 пина далеко (10, 50, 110). Если сброс
  произойдёт — значит чтение этого диапазона недопустимо само по себе.
*/
STATIC
VOID
UggPinOnce (
  VOID
  )
{
  STATIC CONST UINTN  Pins[] = { 89, 90, 91, 92, 93, 10, 50, 110 };
  UINTN               I;
  UINTN               Y = 300;
  UINT32              Level;

  UggDrawText (16, 280, "single-shot TLMM read:");
  for (I = 0; I < sizeof (Pins) / sizeof (Pins[0]); I++) {
    UggDrawText (16, Y, "pin:");
    UggHex (64, Y, Pins[I]);
    UggDrawText (128, Y, "lvl:");
    Level = *(volatile UINT32 *)(UINTN)(UGG_TLMM_BASE + 0x1000 * (Pins[I] + 1) + 4) & 1;
    UggHex (168, Y, Level);
    Y += 20;
  }
  UggDrawText (16, Y + 10, "all reads done");
}
/*
  ============================ ВВОД С КНОПОК ============================

  Реализуем EFI_SIMPLE_TEXT_INPUT_PROTOCOL и своё меню, чтобы кнопки
  работали вне зависимости от BDS/Shell/SimpleInit.

  Источник нажатий — чтение уровней TLMM (только чтение, это проверенно
  безопасно). Опрашиваем пины 88..94: нажатие любой кнопки меняет уровень
  одного из них. Изменение превращается в нажатие клавиши:

      любой пин  -> Стрелка вниз (перевод по меню)
      пин 91     -> Enter (выбор пункта)

  На экране видно: уровни пинов, номер изменившегося пина, счётчик нажатий
  и наше меню с подсветкой — то есть результат нажатий виден сразу.
*/
#define UGG_KEY_FIRST  88
#define UGG_KEY_LAST   94
#define UGG_KEY_COUNT  (UGG_KEY_LAST - UGG_KEY_FIRST + 1)
#define UGG_KEY_QUEUE  16

STATIC UINT8                             mKeyPrev[UGG_KEY_COUNT];
STATIC BOOLEAN                           mKeyPrevValid = FALSE;
STATIC UINTN                             mKeyChangedPin = 0xFFFF;
STATIC UINT8                             mKeyNowLevel = 1;
STATIC UINT8                             mKeyDrawn[UGG_KEY_COUNT];
STATIC BOOLEAN                           mKeyDrawnValid = FALSE;
STATIC UINTN                             mKeyPressCount = 0;

STATIC EFI_KEY_DATA                      mKeyQueue[UGG_KEY_QUEUE];
STATIC UINTN                             mKeyHead = 0;
STATIC UINTN                             mKeyTail = 0;
STATIC EFI_EVENT                         mKeyWaitEvent = NULL;
STATIC EFI_SIMPLE_TEXT_INPUT_PROTOCOL    mUggConIn;
STATIC UINTN                             mMenuIndex = 0;
STATIC UINTN                             mMenuChosen = 0xFFFF;
STATIC UINTN                             mKeyHoldPin = 0xFFFF;
STATIC UINTN                             mKeyHoldTicks = 0;
STATIC BOOLEAN                           mKeyHoldActive = FALSE;
STATIC BOOLEAN                           mKeyHoldFired = FALSE;

STATIC
VOID
UggKeyPush (
  IN UINT16  ScanCode,
  IN CHAR16  Unicode
  )
{
  UINTN  Next = (mKeyHead + 1) % UGG_KEY_QUEUE;

  if (Next == mKeyTail) {
    return;                      /* очередь полна — нажатие теряем */
  }
  mKeyQueue[mKeyHead].Key.ScanCode    = ScanCode;
  mKeyQueue[mKeyHead].Key.UnicodeChar = Unicode;
  mKeyQueue[mKeyHead].KeyState.KeyShiftState  = 0;
  mKeyQueue[mKeyHead].KeyState.KeyToggleState = 0;
  mKeyHead = Next;

  if (mKeyWaitEvent != NULL) {
    gBS->SignalEvent (mKeyWaitEvent);
  }
}

STATIC
EFI_STATUS
EFIAPI
UggConInReset (
  IN EFI_SIMPLE_TEXT_INPUT_PROTOCOL  *This,
  IN BOOLEAN                         ExtendedVerification
  )
{
  mKeyTail = mKeyHead;
  /*
    Сбросить событие ожидания. Если этого не делать, после первого нажатия
    событие остаётся сигнальным, ConSplitter/BDS «видят» клавишу, читают
    пустоту и крутятся в холостом цикле — вся система начинает тормозить.
  */
  if (mKeyWaitEvent != NULL) {
    gBS->CheckEvent (mKeyWaitEvent);
  }
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
UggConInReadKeyStroke (
  IN  EFI_SIMPLE_TEXT_INPUT_PROTOCOL  *This,
  OUT EFI_INPUT_KEY                   *Key
  )
{
  if (mKeyTail == mKeyHead) {
    if (mKeyWaitEvent != NULL) {
      gBS->CheckEvent (mKeyWaitEvent);
    }
    return EFI_NOT_READY;
  }
  *Key     = mKeyQueue[mKeyTail].Key;
  mKeyTail = (mKeyTail + 1) % UGG_KEY_QUEUE;

  /* Очередь опустела — обязательно снять сигнал события. */
  if ((mKeyTail == mKeyHead) && (mKeyWaitEvent != NULL)) {
    gBS->CheckEvent (mKeyWaitEvent);
  }
  return EFI_SUCCESS;
}

/* Нарисовать меню: три пункта, подсветка '>' и отмеченный выбор. */
/*
  Меню рисуется один раз; при листании двигается ТОЛЬКО маркер ">".

  Видеопамять некэшируемая: один символ — ~96 отдельных записей в память.
  Полная перерисовка меню (десятки символов) занимала секунды и создавала
  очередь нажатий, которые потом «догоняли». Два символа — мгновенно.
*/
STATIC UINTN  mMarkerDrawn = 0xFFFF;

STATIC
VOID
UggMoveMarker (
  IN UINTN  OldIndex,
  IN UINTN  NewIndex
  )
{
  if (OldIndex < 3) {
    UggDrawChar (32, 600 + OldIndex * 24, ' ');
  }
  UggDrawChar (32, 600 + NewIndex * 24, '>');
  mMarkerDrawn = NewIndex;
}

STATIC
VOID
UggDrawMenu (
  VOID
  )
{
  STATIC CONST CHAR8  *Items[3] = {
    "Boot from eMMC",
    "Boot from USB",
    "UEFI Shell"
  };
  UINTN  I;

  UggDrawText (16, 560, "-- UGG MENU --");
  for (I = 0; I < 3; I++) {
    UggDrawText (48, 600 + I * 24, Items[I]);
  }
  UggMoveMarker (0xFFFF, mMenuIndex);
  UggDrawText (16, 700, "short press: next");
  UggDrawText (16, 720, "hold 1.2s: select");
}

STATIC UINTN                             mPollGap = 0;
STATIC UINTN                             mHoldTicks = 0;
STATIC BOOLEAN                           mHoldFired = FALSE;

STATIC
VOID
UggTimerMeasure (
  VOID
  );

/* Опрос кнопок: чтение уровней 88..94 и превращение изменений в нажатия. */
STATIC
VOID
UggKeysPoll (
  VOID
  )
{
  UINTN   Idx;
  UINTN   Pin;
  UINT32  Level;
  BOOLEAN Changed = FALSE;

  UggTimerMeasure ();

  for (Idx = 0; Idx < UGG_KEY_COUNT; Idx++) {
    Pin   = UGG_KEY_FIRST + Idx;
    Level = *(volatile UINT32 *)(UINTN)(UGG_TLMM_BASE + 0x1000 * (Pin + 1) + 4) & 1;

    if (mKeyPrevValid && ((UINT8)Level != mKeyPrev[Idx])) {
      mKeyChangedPin = Pin;
      mKeyNowLevel = (UINT8)Level;
      mKeyPressCount++;
      Changed = TRUE;
    }
    mKeyPrev[Idx] = (UINT8)Level;

    /* Индикация уровня: рисуем ТОЛЬКО при изменении — иначе каждый опрос
       перерисовывает 21 символ в некэшируемую память, и всё «тупит». */
    if (!mKeyDrawnValid || (mKeyDrawn[Idx] != (UINT8)Level)) {
      mKeyDrawn[Idx] = (UINT8)Level;
      UggDrawChar (24 + Idx * 40, 300, (CHAR8)('0' + (UINT8)Level));
      mKeyDrawnValid = TRUE;
    }
  }
  mKeyPrevValid = TRUE;

  /*
    Логика кнопок:

      * листание срабатывает по ФРОНТУ нажатия (уровень стал 0) и НЕ зависит
        от того, увидели ли мы отпускание — иначе один пропущенный опрос
        блокировал листание навсегда (именно это и «вешало» меню);
      * защита от дребезга: не чаще одного листания в 300 мс;
      * удержание > 1.2 с (любой пин остаётся в 0) = выбор пункта (Enter).

    Диагностика рисуется только при изменении — перерисовка в некэшируемую
    видеопамять каждый опрос и была причиной тормозов.
  */
  {
    BOOLEAN  AnyLow = FALSE;
    UINTN    K;

    for (K = 0; K < UGG_KEY_COUNT; K++) {
      if (mKeyPrev[K] == 0) {
        AnyLow = TRUE;
      }
    }

    if (mPollGap < 1000) {
      mPollGap++;
    }

    if (Changed && (mKeyNowLevel == 0) && (mPollGap > 2)) {
      UINTN  OldIndex = mMenuIndex;

      mPollGap   = 0;
      mHoldTicks = 0;
      mHoldFired = FALSE;
      mMenuIndex = (mMenuIndex + 1) % 3;
      UggKeyPush (0x02, 0x0000);                 /* SCAN_DOWN */
      UggMoveMarker (OldIndex, mMenuIndex);      /* только 2 символа */
    }

    if (AnyLow) {
      if (!mHoldFired) {
        mHoldTicks++;
        if (mHoldTicks > 12) {                   /* 12 * 100 мс = 1.2 с */
          mHoldFired  = TRUE;
          mMenuChosen = mMenuIndex;
          UggKeyPush (0x17, 0x000D);             /* Enter */
          UggDrawText (16, 660, "selected!");
        }
      }
    } else {
      mHoldTicks = 0;
      mHoldFired = FALSE;
    }
  }

}
STATIC
VOID
EFIAPI
UggKeysPollCallback (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UggKeysPoll ();
}

/* Инициализация ввода: событие ожидания, протокол, меню. */
STATIC
VOID
UggInputInit (
  VOID
  )
{
  gBS->CreateEvent (EVT_NOTIFY_WAIT, TPL_NOTIFY, NULL, NULL, &mKeyWaitEvent);

  mUggConIn.Reset         = UggConInReset;
  mUggConIn.ReadKeyStroke = UggConInReadKeyStroke;
  mUggConIn.WaitForKey    = mKeyWaitEvent;

  UggDrawMenu ();
}

/*
  Измерение реального интервала опроса кнопок.

  Читаем аппаратный счётчик ARM (CNTVCT_EL0) и его частоту (CNTFRQ_EL0).
  В каждом колбэке таймера считаем, сколько миллисекунд прошло с прошлого
  вызова, и показываем число на экране.

  Это отвечает на главный вопрос: таймер действительно работает каждые
  50 мс, или платформа растягивает его до секунд (тогда «медленность»
  не в отрисовке, а в разрешении таймера).
*/
STATIC UINT64  mLastCnt = 0;
STATIC UINT32  mCntFreq = 0;
STATIC UINT32  mLastMs  = 0;
STATIC UINT32  mMaxMs   = 0;

STATIC
UINT64
UggReadCnt (
  VOID
  )
{
  UINT64  Val;

  __asm__ __volatile__ ("mrs %0, cntvct_el0" : "=r" (Val));
  return Val;
}

STATIC
UINT32
UggReadCntFreq (
  VOID
  )
{
  UINT64  Val;

  __asm__ __volatile__ ("mrs %0, cntfrq_el0" : "=r" (Val));
  return (UINT32)Val;
}

STATIC
VOID
UggTimerMeasure (
  VOID
  )
{
  UINT64  Now;
  UINT32  Ms;

  if (mCntFreq == 0) {
    mCntFreq = UggReadCntFreq ();
    mLastCnt = UggReadCnt ();
    return;
  }

  Now = UggReadCnt ();
  if (Now > mLastCnt) {
    Ms = (UINT32)(((Now - mLastCnt) * 1000ULL) / (UINT64)mCntFreq);
    mLastMs = Ms;
    if (Ms > mMaxMs) {
      mMaxMs = Ms;
    }
    UggDrawText (16, 380, "poll interval, ms:");
    UggDrawChar (216, 380, (CHAR8)('0' + (mLastMs / 1000) % 10));
    UggDrawChar (236, 380, (CHAR8)('0' + (mLastMs / 100) % 10));
    UggDrawChar (256, 380, (CHAR8)('0' + (mLastMs / 10) % 10));
    UggDrawChar (276, 380, (CHAR8)('0' + mLastMs % 10));
    UggDrawText (16, 400, "max interval, ms:");
    UggDrawChar (200, 400, (CHAR8)('0' + (mMaxMs / 1000) % 10));
    UggDrawChar (220, 400, (CHAR8)('0' + (mMaxMs / 100) % 10));
    UggDrawChar (240, 400, (CHAR8)('0' + (mMaxMs / 10) % 10));
    UggDrawChar (260, 400, (CHAR8)('0' + mMaxMs % 10));
  }
  mLastCnt = Now;
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
                  &gEfiSimpleTextInProtocolGuid,
                  &mUggConIn,
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
  /* Ввод с кнопок: протокол + таймер опроса (без него меню не работает). */
  UggInputInit ();
  {
    EFI_EVENT  TimerEvent = NULL;

    gBS->CreateEvent (EVT_TIMER | EVT_NOTIFY_SIGNAL, TPL_CALLBACK, UggKeysPollCallback, NULL, &TimerEvent);
    if (TimerEvent != NULL) {
      gBS->SetTimer (TimerEvent, TimerPeriodic, 500000);   /* 50 мс */
    }
  }

  gBS->ConnectController (Handle, NULL, NULL, TRUE);

  /* Заголовок — признак того, что драйвер дисплея и текстовый вывод живы. */
  UggDrawText (16, 4, "Ugg UEFI  MSM8940  Redmi Note 5A Prime");

  if (FixedPcdGet32 (PcdDebugStageBands) == 6) {
    UggProbeSdcc ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 7) {
    UggSdccInit ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 8) {
    UggSdccDump (300);
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 9) {
    UggSdccInit2 ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 10) {
    UggSdccInit3 ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 11) {
    UggSdccPowerProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 12) {
    UggSdccClockInit ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 13) {
    UggSdccInit4 ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 14) {
    UggSpmiProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 15) {
    UggSpmiProbe2 ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 16) {
    UggSpmiReadProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 17) {
    UggSpmiLookupProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 18) {
    UggSpmiXfer ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 19) {
    UggSpmiWindowProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 20) {
    UggSpmiWriteProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 21) {
    UggSpmiAddrProbe ();
  }

  if (FixedPcdGet32 (PcdDebugStageBands) == 23) {
    UggPinOnce ();
  }

  if ((FixedPcdGet32 (PcdDebugStageBands) == 2) || (FixedPcdGet32 (PcdDebugStageBands) == 5) || (FixedPcdGet32 (PcdDebugStageBands) == 22)) {
    Status = gBS->CreateEvent (
                    EVT_TIMER | EVT_NOTIFY_SIGNAL,
                    TPL_CALLBACK,
                    ((FixedPcdGet32 (PcdDebugStageBands) == 5) ? (EFI_EVENT_NOTIFY)UggKeyPollCallback : ((FixedPcdGet32 (PcdDebugStageBands) == 22) ? (EFI_EVENT_NOTIFY)UggPinScanCallback : (EFI_EVENT_NOTIFY)UggFbRedrawCallback)),
                    NULL,
                    &mRedrawTimer
                    );
    if (!EFI_ERROR (Status)) {
      gBS->SetTimer (mRedrawTimer, TimerPeriodic, 200000);   /* 0.5 c */
    }
  }

  return Status;
}
