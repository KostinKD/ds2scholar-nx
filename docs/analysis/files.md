# Файлы SotFS: контейнеры, архивы, звук, видео (этап 1)

Сравнение — с обычной DS2 TU0 (`G:\DS2Switch\ds2-nx\assets\game_root`, факты —
[docs/ds2-nx/analysis/files.md](../ds2-nx/analysis/files.md)). Перепись архивов и сравнение файлов сделаны
одноразовыми скриптами сессии 2026-10-21; результаты — `logs/game_root_files.log`, `logs/files_vs_ds2.log`,
`logs/bhf4_census.log`, `logs/stfs_list_compat4.log`.

## Что лежит в `G:\DSII Scholar of the First Sin_TorFiles.RU\465307E4`

| Папка | Файл | Что |
|---|---|---|
| `00007000` (Games on Demand) | `1807A1F14E760EA83429` + `.data\Data0000…0034` | игра, SVOD |
| `00000002` (Marketplace content) | `D4B91B6B4DA1509C280F56F77B09203DE7D39AE646` (1 233 395 712 байт) | **DLC-каталог «DARK SOULS II Compatibility Pack 4»** |

### GoD-пакет игры

| Поле | Значение | Смещение |
|---|---|---|
| magic / content type | `LIVE` / `0x00007000` | 0x000 / 0x344 |
| title id / media id | `465307E4` / `458B3E06` | 0x360 / 0x354 |
| version / base | 0 / 0 | 0x358 / 0x35C |
| volume | 1 = SVOD, флаги `0x00` (не enhanced GDF) | 0x3A9 / 0x379+0x18 |
| data files | 35, 5 922 250 752 байт | 0x39D / 0x3A1 |
| имя | `DARK SOULS II Scholar of the First Sin [X360-CLUB]` (переписано релиз-группой) | 0x411 |

`python -I tools/god_extract.py "<…>\00007000\1807A1F14E760EA83429"` → `assets/game_root` (`logs/god_extract.log`):
**123 файла, 19 папок, 5 892 933 534 байт**; поток данных 5 893 218 304 — не обрезан. Проверка: `Default.xex`
расшифровывается в валидный PE ([xex.md](xex.md)), у BHD/BDT суммы payload сходятся с BDT (ниже).
Замечание по инструменту: в конце вывод `extract_iso.py` пишет «this port is written for Mass Effect 1
(Title ID 4D5307E8)» — устаревшая проверка из другого порта, на распаковку не влияет (поправить отдельно).

### <a id="dlc"></a>Пакет `00000002` — DLC-каталог

| Поле | Значение |
|---|---|
| magic / content type | `PIRS` / `0x00000002` (marketplace content), STFS, read-only, 299 338 блоков |
| title id | `465307E4`; media id/version 0 |
| имя / описание | `DARK SOULS II Compatibility Pack 4` / «This is a free compatibility pack for DARK SOULS II online users. It is required for online play.» |

Содержимое (`python -I tools/stfs_extract.py <пакет> <папка> --list`, 49 записей):
- `Data\catalog\DlcData010306_110.bhd/.bdt` — архив `BHF4`/`BDF4`, версия `00010300`, **5 678 файлов**, payload
  1 108 435 261 байт (+48 заголовок = размер BDT ✓). Карты: **все 24 базовые** (`.msb` и др.) **и 4 карты DLC
  `m50_35`, `m50_36`, `m50_37`, `m50_38`** (180 записей m50_3x); папки timeact, model, ezstate, PrefabEditor,
  param, menu, sound, morpheme4, map, sfx, `regulation.bnd.dcx`.
- `Data\catalog\sound\*.fsb` — 43 банка `FSB5` v1, codec 10 (XMA), в т. ч. `frpg2_sm5035…5038`, `frpg2_xm5035…5038`.
- `Data\License\license32.bin` — текст `DARK SOULS II DLC Catalog`.

Связь с кодом SotFS: имя совпадает с шаблоном `dlc_catalog:/DlcData%06d_%03d.bhd` и `Data\Catalog\DlcData??????_???.bhd`
(0x8210ACDA), корень `dlc_root:/data/catalog`. В архивах на диске SotFS карт `m50_*` **нет** (ниже).

**Пакет обязателен** (PC-запуск 2026-10-21): без него после «PRESS START» игра пишет «Unable to start DARK SOULS II
because the Compatibility Pack is missing…» и дальше не идёт (`logs/boot_test2.log`). С пакетом перечисляет
`00000002`, открывает его как `dlc_temp`, затем `dlc_root` (`XamContentCreate … type 00000002 mode 3 -> open`) и
читает `dlc_root:\data\catalog\DlcData010306_110.bhd/.bdt` (`logs/boot_test4.log`), затем «No Ethernet cable» →
офлайн → главное меню.

Где лежит для порта: распакованной папкой (`tools/stfs_extract.py`) в
`<user data>\0000000000000000\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646\Data\…`
(пакеты marketplace ищутся у xuid 0). Копия — `assets/content/…` (в `.gitignore`), в `out/pc/userdata` подключена
junction'ом. Без `.header` SDK раньше отдавал игре неинициализированную запись (пустое имя): исправлено в
`sdk/src/system/xam/content_manager.cpp` (`XSUCCEEDED` применялся к X_RESULT). Монтируется ли пакет ещё и как
`gamedata_patch:`/`title_patch:`/`patch_binder:`, грузятся ли карты DLC — **не проверено**. На Switch — путь на SD
не проверен.

## Содержимое образа: SotFS против DS2

Набор файлов тот же, что у DS2 (121 файл), плюс два:
- `regulation_v100.bnd.dcx` (674 750 байт) — **побайтно равен `regulation.bnd.dcx` обычной DS2** (SHA-1
  `a797449b…`); путь в коде `title:/regulation_v100.bnd.dcx` (0x82026A94). Текущая регуляция SotFS —
  `regulation.bnd.dcx` (826 432 байт, `DCX`/`DFLT`).
- `movie/Thumbs.db` (OLE, 4096 байт) — мусор Windows из дампа, игре не нужен.

Из 121 общего файла **104 побайтно совпадают с DS2** (SHA-1): `movie/prologue.wmv`, все 71 `sound/*.fsb`, `.mch/.mix/.rpc`,
`frpg2_efx.fev`, `shader/Filter.bnd`, `FeShader.bnd`, `SfxShader.bnd`, `shader/Simple/*.fxo`, `font/*.fxo`,
10 из 11 шрифтов, `param/SoundResidentParam`, `SoundSpecialEquipmentParam`, `AvatarAssetPack`, `$SystemUpdate/*`.
Отличаются (`logs/files_vs_ds2.log`):

| Файл | DS2 → SotFS |
|---|---|
| `Default.xex` | 21 905 408 → 22 167 552 |
| `GameData1.bhd/.bdt` | 11 880 → 9 865 записей; 2,84 → 2,72 ГБ |
| `GameData2.bhd/.bdt` | 10 951 → 8 939 записей; 2,46 → 2,34 ГБ |
| `regulation.bnd.dcx` | 674 750 → 826 432 |
| `shader/FlverShader.bnd` | 2 203 → 1 904 шейдера: 962 побайтно те же, 739 изменены, 502 убраны, 203 новых (напр. `Cheap\Flver_…ClothIbl…`) |
| `shader/Decal.bnd` | 18 → 18: 12 те же, 6 изменены (`Decal_Dif*.fpo`) |
| `sfx/sfx9999*.ffxbnd(.dcx)` | крупнее на 5–10 % |
| `param/ModelLinkLodTypeParam`, `SoundFootParam`, `SoundObjectBreakParam` | крупнее |
| `sound/frpg2_stationary.fev` | тот же размер, другое содержимое |
| `font/Portuguese/FeFont_Small.fontbnd.dcx`, `nxeart` | мелкие изменения |

Для пакета шейдеров: контейнеры, совпавшие байт в байт, дадут те же шейдеры, что у DS2; новые/изменённые
FlverShader (~940) собирать из `shader_misses/` SotFS. BND4 `FlverShader.bnd` той же версии `10G29R1`. Магия
`.fpo/.vpo` внутри новых записей — **не проверено**.

## Архивы BHF4/BDF4 (GameData1/2)

Формат тот же, что у DS2: BXF4 split binder, big-endian, без шифрования, имена Shift-JIS, запись 0x18 байт.

| Поле BHF4 | GameData1 | GameData2 |
|---|---|---|
| файлов (0x0C) | 9 865 (DS2: 11 880) | 8 939 (DS2: 10 951) |
| версия (0x18) | `14L26V47` (DS2: `14B27P44`) | `14L26W1` (DS2: `14B27P55`) |
| unicode / format | 0 / `0x0C` | 0 / `0x0C` |
| payload / BDT | 2 717 152 760 / 2 717 152 808 | 2 337 225 296 / 2 337 225 344 |

- Разница payload и BDT — 48 байт (`BDF4`), как у DS2.
- Карты (`.msb`) — **те же 24**, что у DS2, и так же разделены: GameData1 — m10_02/04/10/16/17/18/19/23/25/30/31/34,
  m20_10; GameData2 — m10_14/15/27/29/32/33, m20_11/21/24/26, m40_03. Карт DLC (`m50_*`) и `model_hq` нет.
- DCX: все 4 856 + 4 407 = 9 263 — `DFLT` (zlib), EDGE/KRAK нет.
- Форматы внутри — те же (DCX, TPF, TAE, FSSL/ESD, PFBB, BND4, вложенные BHF4/BDF4, OBJB, filt, EVD, FMG, PARAM);
  `logs/bhf4_census.log`. Почему записей меньше (убраны дубликаты?) — **не разбиралось**.

## Звук

Все 71 `sound/*.fsb` побайтно равны DS2 → FSB5 v1, codec 10 = **XMA**, FMOD Ex 4.40.05 ([xdk.md](xdk.md)).
Из `.fev` изменён только `frpg2_stationary.fev`. Банки DLC — в пакете `00000002` (тоже FSB5/XMA).

## Видео

`movie/prologue.wmv` побайтно равен DS2: ASF, **WMV3** 1280×720 + WMA 10 Pro 5.1, 254,3 с. Путь
`title:/movie/prologue.wmv` (0x820295AC). Других роликов нет.
