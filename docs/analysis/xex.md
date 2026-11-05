# Default.xex SotFS — анализ (этап 1)

Источник: `assets/game_root/Default.xex` (22 167 552 байт, SHA-1 `a3e7f5f4970e13d5b5d25f947e393a04afe49449`),
распакован из GoD `G:\DSII Scholar of the First Sin_TorFiles.RU\465307E4\00007000\1807A1F14E760EA83429`
(см. [files.md](files.md)). Сравнение — с `G:\DS2Switch\ds2-nx\assets\game_root\Default.xex` (обычная DS2 TU0,
SHA-1 `261848cb…`, факты — [docs/ds2-nx/analysis/xex.md](../ds2-nx/analysis/xex.md)).

Воспроизвести:

```
python -I tools/god_extract.py "G:\DSII Scholar of the First Sin_TorFiles.RU\465307E4\00007000\1807A1F14E760EA83429"   # logs/god_extract.log
python -I tools/xex_headers.py assets/game_root/Default.xex                                                         # logs/xex_headers.log
```

Расшифровка/распаковка PE, разбор секций, импортов и строк сделаны одноразовыми скриптами сессии 2026-10-21
(AES через Windows bcrypt, basic-сжатие; в репозиторий не сохранены, как и в ds2-nx). Проверка скриптов: на xex
DS2 они дают ровно факты из docs DS2 (MZ, 0x16C0000, 9 секций, 210/353 импорта, тот же единственный вызов
`XexLoadImage` на 0x8299FEC8). Результаты: `logs/pe_info_sotfs.log`, `logs/pe_u16_sotfs.log`, `logs/xex_imports.log`,
`logs/xex_loadimage_callers.log`.

## Идентификация

| Поле | SotFS | DS2 TU0 | Доказательство |
|---|---|---|---|
| Title ID | `465307E4` | `465307E4` | execution info (`0x00040006`) +0x0C; GoD header 0x360 |
| Media ID | **`458B3E06`** | `72EA8B94` | execution info +0x00; GoD header 0x354 |
| Version / base version | **`0.0.0.22` / `0.0.0.22`** | 8 / 8 | execution info +0x04/+0x08 — равны → XEX не патчен |
| Диск | 1 из 1 | 1 из 1 | execution info |
| Исходное имя PE | `FRPG2.exe` | `FRPG2.exe` | opt. `0x000183FF` |
| Время линковки | **`0x5475BA38` = 2014-11-26 11:32:08 UTC** | 2014-01-27 | opt. `0x00018002`; тот же timestamp в COFF-заголовке PE |
| Имя в GoD-заголовке | `DARK SOULS II Scholar of the First Sin [X360-CLUB]` | `DARK SOULS II` | GoD header 0x411 — переписано релиз-группой, к игре не относится |

## Title Update

**TU не применён (базовая версия с диска).** Доказательства: в `465307E4\` нет папки `000B0000`; в XEX нет
`0x000005FF` (delta patch); version == base version; в GoD header version/base = 0. В главном меню игра
показывает **Ver.1.10, Calibrations 1.13** (PC-сборка, эмулируемый GPU, 2026-10-21, `logs/boot_test5.log`, снимок
на 135-й секунде; у DS2 TU0 — Ver.1.00 / 1.00). В PE имя онлайновой регуляции — `regulation_0114.bin`
(0x82011F0C; у DS2 TU0 — `regulation_0101.bin`).

## Загрузка и раскладка образа

| Поле | SotFS | DS2 TU0 |
|---|---|---|
| Module flags | `0x00000001` (title) | то же |
| Image base | `0x82000000` | то же |
| **Entry point** | **`0x829C3DE0`** | `0x82993BB0` |
| **Image size** | **`0x016F0000`** (24 051 712) | `0x016C0000` |
| Шифрование / сжатие | AES retail / basic | то же |
| Stack size | 256 КБ | то же |
| TLS | 64 слота, raw data **`0x83674E00`**, 1460 байт | 64, `0x83643A00`, 1460 |
| System flags | `0x00000600` | то же |
| Ресурс (SPA/XDBF) | `465307E4` @ **`0x83680000`**, 443 025 байт | @0x83650000, 435 802 |
| Security: region / allowed media / image flags | `0xFFFFFFFF` / `0x00000004` / `0x00000008` | то же |
| Page descriptors | 367 | 364 |
| Opt. headers | 15 (те же ключи + game ratings, LAN key, logo) | — |

Проверка расшифровки: PE начинается с `MZ`, длина ровно 0x16F0000.

### Секции PE (machine `0x01F2`)

| Секция | VA SotFS | Размер SotFS | VA DS2 | Размер DS2 |
|---|---|---|---|---|
| .rdata | 0x82000400 | 0x01CDE94 | 0x82000400 | 0x01CA244 |
| .pdata | 0x821CE400 | 0x006B590 | 0x821CA800 | 0x0069ED0 |
| .text | 0x82240000 | **0x11F8264** | 0x82240000 | 0x11C2474 |
| .data | **0x83440000** | 0x0234C9C | 0x83410000 | 0x02339DC |
| .tls | 0x83674E00 | 0x00005B5 | 0x83643A00 | 0x00005B5 |
| .XBMOVIE | 0x83675400 | 0x000000C | 0x83644000 | 0x000000C |
| .idata | 0x83680000 | 0x0000508 | 0x83650000 | 0x00004F8 |
| .XBLD | 0x83690000 | 0x0000130 | 0x83660000 | 0x0000130 |
| .reloc | 0x83690200 | 0x00EC07C | 0x83660200 | 0x00E8EA8 |

- `.text` больше на 0x35DF0 (~220 КБ); `.pdata` — 54 962 функции против 54 234 у DS2 (+728).
- Все адреса кода и данных сдвинуты: в `.text` сдвиг растёт от +0x2E40 (начало) до ~+0x30000 (0x826…–0x82D…) и
  ~+0x35000 (0x82F…–0x833…); `.data` — +0x30000. **Ни один адрес из ds2-nx не годится напрямую.**

## Сопоставление функций с DS2 (по маскированной сигнатуре)

Функции из `.pdata` обеих игр сравнены по байтам с маской (обнулены смещения `b`/`bc`, непосредственные значения
`addi`/`addis` и смещения D-form load/store). Из 54 234 функций DS2: **31 379 нашли ровно одного двойника** в SotFS,
20 478 — несколько (мелкие/повторяющиеся функции), **2 377 (4,4 %) — ни одного** (изменённый код). Сдвиги по
участкам — таблица в журнале сессии (2026-10-21). Это основа этапа 2/4: большинство адресов DS2 переводится
сопоставлением, но каждое совпадение подтверждать (вызывающие, константы).

Найденные адреса DS2 → SotFS из docs/ds2-nx (все — единственный кандидат; `logs/sigmatch_d3d.log`):

| Что (DS2) | DS2 | SotFS | |
|---|---|---|---|
| memcpy XDK (`ds2_native_memcpy`) | 0x82997E24 | **0x829C7FF4** | байты идентичны (0x4CC) |
| ожидание GPU (`ds2_gpu_wait`) | 0x829B9C60 | 0x829E9E28 | |
| обработчик прерываний GPU | 0x829A7F70 | 0x829D8140 | |
| D3D-функции | см. [xdk.md](xdk.md#d3d) | | |

Нативные замены в `app/src/cpu` проверяют хеш гостевого кода — перенос адресов в код только с записью
доказательства (этап 2/5). **Не проверено:** что найденные адреса вызываются в рантайме SotFS.

## Импорты

| Модуль | Версия (min) | SotFS (записей/функций) | DS2 |
|---|---|---|---|
| xam.xex | 2.0.21256.0 (2.0.16537.0) | 218 / 109 | 210 / 105 |
| xboxkrnl.exe | 2.0.21256.0 (2.0.16537.0) | 353 / 170 | 353 / 170 |

Ординалы разрешены по `sdk/src/kernel/*/export_table.inc` (`logs/xex_imports.log`). Новые у SotFS (только xam):
`XamUserGetMembershipTierFromXUID` (0x217), `XamUserGetOnlineCountryFromXUID` (0x218),
`XamShowMarketplaceDownloadItemsUI` (0x2E7), `XamGetLanguage` (0x3D2). Набор xboxkrnl совпадает с DS2.
Есть ли у SDK реализации/заглушки этих четырёх — **не проверено** (этап 3).

## Дополнительные .xex-модули

**Нет: `[[modules]]` в манифесте не нужен** — картина та же, что у DS2.

- На образе один исполняемый файл (`Default.xex`).
- Прямые `bl` к thunk'у `XexLoadImage` (0x83437CF4): **один**, 0x829D0098 в обёртке `0x829D0080` (0x44 байта по
  `.pdata`). Её вызывают два места, обе с константным системным именем: 0x829F1560 → r3 = 0x82078C98
  `"xboxkrnl.exe"`, 0x82C6597C → r3 = 0x82032134 `"xam.xex"`.
- `XexGetModuleHandle` (thunk 0x83437754): 5 вызовов — 0x826D515C, 0x826D53B0, 0x829C7924, 0x829D0550, 0x82C57F90.
  Обёртка `0x829D0540` вызывается 4 раза, все с `"xam.xex"`.
- `XexGetProcedureAddress` (thunk 0x83437744): 5 вызовов; обёртку `0x829D0010` зовут с `"xam.xex"`/`"xboxkrnl.exe"`,
  четыре вызова на 0x82C659B0…E0 — r3 не константа (вероятно, хендл предыдущего вызова — **не проверено**).
- Строки `*.xex` в PE: только `xam.xex`.

Не проверено: косвенные вызовы через указатель на thunk; окончательно — логом `XexLoadImage_entry` в рантайме.
Мелочь: в docs DS2 места вызова обёртки указаны как 0x829C1378/0x82C359E8, скан даёт 0x829C1398/0x82C35A14
(строки те же) — в DS2-доках, вероятно, указано начало блока, не сам `bl`.

## Что ещё нашлось в строках (влияет на порт)

Из диффа UTF-16BE путей DS2 → SotFS (`logs/pe_u16_sotfs.log`, 389 строк против 327):
- **DLC из marketplace-контента:** `dlc_root:/data/catalog`, `dlc_catalog:/DlcData%06d_%03d.bhd`,
  `Data\Catalog\DlcData??????_???.bhd` (ASCII, 0x8210ACDA), `dlc_data:/…` (карты, модели, звук, регуляция),
  `title:/DlcData.bhd`/`.bdt`, `install:/Install/DlcData.bhd`. На диске `DlcData.*` нет — см. [files.md](files.md#dlc).
- **Патч-слой поверх архивов:** `gamedata_patch:/…`, `title_patch:/…` (шейдеры, шрифты, `regulation.bnd.dcx`),
  `patch_binder:/…`. Куда они монтируются (на DlcData?) — **не проверено**.
- `title:/regulation_v100.bnd.dcx` (новый файл на диске, см. files.md), `install:/` — поддержка установки на HDD.
- `model_hq`/`sfx_hq`/`objhq:`/`partshq:` — пути «HQ»-моделей; на диске их нет (общий код с PC/PS4-версией?
  **не проверено**).
- Убраны из `title:/`: `title:/shader/FlverShader.bnd`, `Decal.bnd`, `SfxShader.bnd` и др. теперь грузятся через
  `title_patch:/`; файлы на диске те же.
