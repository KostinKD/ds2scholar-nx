# Файлы игры: контейнер, архивы, звук, видео (этап 1)

## Исходный контейнер — Games on Demand (SVOD)

`G:\DS2Switch\game\465307E4\00007000\5D80A14F861D50C6E2B3` + папка `.data\Data0000…Data0036`.

| Поле заголовка | Значение | Смещение |
|---|---|---|
| magic | `LIVE` | 0x000 |
| content type | `0x00007000` (Games on Demand) | 0x344 |
| title id / media id | `465307E4` / `72EA8B94` | 0x360 / 0x354 |
| volume type | 1 = SVOD | 0x3A9 |
| SVOD flags | `0x00` (не enhanced GDF) | 0x379+0x18 |
| data files | 37, 6 161 911 808 байт | 0x39D / 0x3A1 |

Раскладка внутри `Data0000`: `XSF\x1a` по 0x2000, магия XDVDFS `MICROSOFT*XBOX*MEDIA` по физ. 0x12000 — это
логический сектор 32 после снятия двух хеш-таблиц (L1 + L0), т. е. обычный XDVDFS с базой 0.

Ни `extract_iso.py` (только .iso), ни `stfs_extract.py` (только STFS; на SVOD падает с `volume is SVOD`) это не
читали, поэтому добавлен **`tools/god_extract.py`**: склеивает блоки данных из `DataNNNN` (без хеш-таблиц) в
один поток и обходит XDVDFS кодом `extract_iso.py`. Хеши SVOD не проверяются.

```
python tools/god_extract.py G:/DS2Switch/game/465307E4/00007000/5D80A14F861D50C6E2B3 --list   # logs/god_list.log
python tools/god_extract.py G:/DS2Switch/game/465307E4/00007000/5D80A14F861D50C6E2B3          # → assets/game_root
```

Результат: 121 файл, 19 папок, 6 131 414 015 байт → `assets/game_root` (в `.gitignore`). Сумма размеров файлов
меньше длины потока данных (6 131 699 712) — поток не обрезан. Проверка корректности: `Default.xex` начинается с
`XEX2`, все заголовки разбираются, PE расшифровывается в валидный `MZ` нужного размера; у BHD/BDT суммы payload
сходятся с размерами BDT (ниже).

## Содержимое образа

| Путь | Что | Формат (доказательство — первые байты) |
|---|---|---|
| `Default.xex` | исполняемый файл | `XEX2`, см. [xex.md](xex.md) |
| `GameData1.bhd` + `.bdt` | основной архив, 11 880 записей, 2,84 ГБ | `BHF4` / `BDF4` |
| `GameData2.bhd` + `.bdt` | основной архив, 10 951 запись, 2,46 ГБ | `BHF4` / `BDF4` |
| `regulation.bnd.dcx` | параметры баланса | `DCX\0` + `DFLT` |
| `param/*.param` (5) | параметры звука/LOD вне архива | DS2 PARAM (BE), имя типа на 0x0C (`SOUND_FOOT_PARAM`) |
| `shader/*.bnd` | шейдерные бандлы | `BND4` BE, версия `10G29R1`, UTF-16 имена |
| `shader/Simple/*.fxo`, `font/*.fxo` | одиночные шейдеры Xenos | `0x102A1100` (pixel) / `0x102A1101` (vertex) |
| `font/<язык>/FeFont_Small.fontbnd.dcx` | шрифты, 11 языков | `DCX` + `DFLT` |
| `sfx/*.ffxbnd(.dcx)` | эффекты | `BND4` / `DCX` |
| `sound/*.fsb` (71) | банки FMOD | `FSB5` v1, codec 10 = **XMA** у всех 71 |
| `sound/*.fev` (2) | события FMOD Designer | `FEV1` |
| `sound/frpg2_multich.mch` и др. `.mix/.rpc` | данные FMOD Event | `MOFC` и т. п. — не разбирались |
| `movie/prologue.wmv` | единственный ролик | ASF, см. «Видео» |
| `AvatarAssetPack` | награды-аватары | `PIRS`, content `0x00008000`, title `FFFE07DF`; внутри `AvatarAssetPack.toc` |
| `nxeart` | фон/иконка дашборда | `PIRS`, content `0x00030000`; `nxebg.jpg`, `nxeslot.jpg`, `DashStyle` |
| `$SystemUpdate/` | системное обновление консоли | `PIRS`, content `0x000B0000`, title `FFFE07D1` — не игра |

Последние три для порта не нужны (дашборд/система). Списки PIRS получены `tools/stfs_extract.py <файл> <out> --list`.

## Архивы BHF4/BDF4 (GameData1/2)

Это **не** BHD5 из ПК-версии DS2: формат BXF4 (split binder), **big-endian, без шифрования, имена файлов
открытым текстом (Shift-JIS)**.

| Поле BHF4 | GameData1 | GameData2 |
|---|---|---|
| байт 0x09 (big-endian) | 1 | 1 |
| файлов (0x0C, BE) | 11 880 (0x2E68) | 10 951 (0x2AC7) |
| версия (0x18) | `14B27P44` | `14B27P55` |
| размер записи (0x20) | 0x18 | 0x18 |
| unicode (0x30) / format (0x31) | 0 / `0x0C` (имена) | 0 / `0x0C` |
| сумма payload / размер BDT | 2 837 020 089 / 2 837 020 137 | 2 457 192 474 / 2 457 192 522 |

Запись 0x18 байт: `u8 flags (0x02), 3×pad, i32 -1, u64 size, u32 data offset, u32 name offset`. Разница
payload и BDT в обоих — 48 байт = заголовок `BDF4` (первая запись начинается со смещения 0x30).

Пути в коде: `title:/GameData1.bhd` (0x82014F81), `title:/GameData2.bhd` (0x82014F41), шаблон `%s%s.bdt`
(0x820360E1); содержимое монтируется как `gamedata:/` (`gamedata:/sound/frpg2_smain.bnd` и др.).

Разделение по картам: 7 512 файлов (меню, тексты, общие модели) лежат **в обоих** архивах с одинаковыми
размерами; специфичные для карт — в одном из них (2 281 только в GameData1, 1 649 только в GameData2;
например `breakobj\m10_02_00_00` только в 1, `breakobj\m10_14_00_00` только в 2). Похоже на дублирование под
два слоя DVD — вывод, не проверено.

Внутренние форматы (по первым 4 байтам записей, полный перечень — `logs/bhf4_census.log`):

| Формат | Где | Магия |
|---|---|---|
| DCX/DFLT (zlib) | `.bnd`, `.texbnd`, `.anibnd.dcx`, `.msb`, `.ngp`, `.edd`… | `DCX\0`; метод сжатия у **всех** 9 283 DCX в архивах и 13 на диске — `DFLT` |
| BND4 | вложенные бандлы | `BND4` |
| BHF4/BDF4 вложенные | `.mapbhd/.mapbdt`, `.tpfbhd/.tpfbdt`, `.hkxbhd/.hkxbdt`, `.gibhd/.gibdt` | `BHF4`/`BDF4` |
| TPF | текстуры (3 558 на архив) | `TPF\0` |
| FMG | тексты | `00 01 00 00` |
| TAE | анимационные события | `TAE ` |
| ESD | AI/скрипты ezstate | `FSSL` |
| EMEVD | события | `EVD\0` |
| PFBBIN, OBJB, `filt`, VSDF | префабы, разрушаемые объекты, фильтры, voice sync | соответствующие магии |
| PARAM | параметры | без магии (u32 BE на 0x00) |
| DDS, PNG, INI | единичные файлы | стандартные |

DCX: `DCX\0 00010000`, блок `DCS` (несжатый/сжатый размер BE), блок `DCP` + `DFLT`. Распаковка — zlib (в игре
zlib 1.2.7, см. [xdk.md](xdk.md)). Отдельного алгоритма (EDGE/KRAK) нет.

Census-скрипт одноразовый (папка сессии), его логика: пройти записи BHF4, прочитать 4 байта по смещению в BDT,
сгруппировать по расширению; для DCX — байты 0x28..0x2C.

## Звук

- FMOD Ex 4.40.05 + FMOD Event (`.fev`). Все 71 банк — `FSB5` версии 1, поле codec (0x18) = 10 = XMA
  (по enum FSB5). XMA на Switch нужно будет декодировать (у ReXGlue/xenia есть XMA-декодер — не проверено,
  как он подключён в sdk).
- `sound/frpg2_ps*.fsb` — короткие, `frpg2_sm*.fsb` — крупные (по картам), `frpg2_xm*.fsb` — третья группа;
  назначение групп не разбиралось.

## Видео

Один ролик: `movie/prologue.wmv` (297 972 312 байт), путь в коде `title:/movie/prologue.wmv` (0x82026571).

| Поле | Значение | Доказательство |
|---|---|---|
| контейнер | ASF | GUID `3026B275-8E66-CF11…` в начале файла |
| видео | **WMV3** (Windows Media Video 9, «Professional»), 1280×720 | BITMAPINFOHEADER @0x14F2 (biCompression `WMV3`), Codec List Object |
| аудио | **WMA 10 Professional** (`wFormatTag 0x0162`), 5.1, 48 кГц, 440 кбит/с, 2-pass CBR | Stream Properties, Codec List Object |
| длительность | 254,3 с; max bitrate 10 475 760 бит/с | File Properties Object |

Проигрывание на 360 — через XMedia (static libs `XMCORE`, `XWMAD`; секция `.XBMOVIE`). Для порта нужен
декодер WMV3 + WMA Pro (например, FFmpeg) или замена ролика — решение не принималось.

## Другие точки монтирования

Из строк PE: `title:` (корень диска), `gamedata:` (содержимое BHD), `temp:` (`temp:/cache.bin`, кэш на
utility-разделе), `system:/system.properties`, `cache:`, `game:`; также логические `param:`, `map:`, `menu:`,
`chr:`, `parts:`, `obj:`, `ezstate:`, `mapbnd:`, `gibnd:`, `tpfbnd:`. Как их резолвит игра — не разбиралось.
