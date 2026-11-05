# Default.xex — анализ (этап 1)

Источник: `assets/game_root/Default.xex` (21 905 408 байт), распакован из GoD-пакета
`G:\DS2Switch\game\465307E4\00007000\5D80A14F861D50C6E2B3` (см. [files.md](files.md)).

Воспроизвести:

```
python tools/god_extract.py G:/DS2Switch/game/465307E4/00007000/5D80A14F861D50C6E2B3   # → logs/god_extract.log
python tools/xex_headers.py assets/game_root/Default.xex                               # → logs/xex_headers.log
```

## Идентификация

| Поле | Значение | Доказательство |
|---|---|---|
| Title ID | `465307E4` | XEX opt. header `0x00040006` (execution info) +0x0C; совпадает с `0x360` в заголовке GoD и с именем папки `game\465307E4` |
| Media ID | `72EA8B94` | execution info +0x00; GoD header `0x354` |
| Version / base version | `0x00000008` / `0x00000008` | execution info +0x04 / +0x08 (равны → XEX не патчен) |
| Диск | 1 из 1, platform 0, exe type 0, savegame id 0 | execution info +0x10..+0x17 |
| Исходное имя PE | `FRPG2.exe` | opt. header `0x000183FF` |
| Время линковки | `0x52E5E5FF` = 2014-01-27 04:52:15 UTC | opt. header `0x00018002`; тот же timestamp в COFF-заголовке PE |
| Отображаемое имя | `DARK SOULS II` | GoD header `0x411` (UTF-16BE) |

Префикс `0x4653` = ASCII `FS` — по соглашению это код издателя FromSoftware (вывод, не проверено по базе
Title ID).

## Title Update

**TU не применён — это базовая версия с диска (TU0).** Доказательства:

1. В `G:\DS2Switch\game\465307E4\` есть только `00007000` (Games on Demand). Папки `000B0000` (Title Update) нет.
2. В XEX нет opt. header `0x000005FF` (delta patch descriptor), version == base version == `0x00000008`.
3. В GoD-заголовке version/base version = 0.
4. На образе нет `.xexp` (полный список — [files.md](files.md)).

Проверено в рантайме (2026-10-16, PC-сборка, снимок главного меню): игра показывает **Ver.1.00, Calibrations 1.00**. В PE есть строка
`regulation_0101.bin` (0x82010714) — вероятно, имя файла регуляции, качаемого онлайн; на диске лежит
`regulation.bnd.dcx`.

Флаг `TU x` в CLAUDE.md заменён на `TU0 (диск, без TU)`. Если позже появится TU — нужен отдельный
`.xexp`, и всё ниже придётся перепроверить.

## Загрузка и раскладка образа

| Поле | Значение | Источник |
|---|---|---|
| Module flags | `0x00000001` (title) | XEX +0x04 |
| Image base | `0x82000000` | opt. `0x00010201`; security info load address |
| Entry point | `0x82993BB0` | opt. `0x00010100` |
| Image size | `0x016C0000` (23 855 104) | security info +0x04 |
| Шифрование | AES-128 (retail key), `encryption=1` | opt. `0x000003FF` |
| Сжатие | basic (`compression=1`, блоки data/zero, не LZX) | opt. `0x000003FF` |
| Stack size | 256 КБ | opt. `0x00020200` |
| TLS | 64 слота, raw data `0x83643A00`, 1460 байт | opt. `0x00020104` |
| System flags | `0x00000600` | opt. `0x00030000` |
| Ресурс | `465307E4` @ `0x83650000`, 435 802 байт (SPA/XDBF) | opt. `0x000002FF` |
| Security: image flags | `0x00000008` | sec. info +0x10C |
| Security: region | `0xFFFFFFFF` (все регионы) | sec. info +0x178 |
| Security: allowed media | `0x00000004` | sec. info +0x17C |
| Page descriptors | 364 | sec. info +0x180 |
| LAN key | присутствует (`0x00040404`) | |

Проверка расшифровки: PE расшифрован (AES-CBC, ключ сессии из sec. info +0x150, расшифрован retail-ключом) и
распакован (basic) во временную папку сессии — результат начинается с `MZ`, длина ровно 0x16C0000.
В репозиторий ничего не сохранялось; кодоген ReXGlue делает то же сам.

### Секции PE (machine `0x01F2` = PowerPC BE)

| Секция | VA | Размер | Флаги |
|---|---|---|---|
| .rdata | 0x82000400 | 0x01CA244 | 0x40000040 |
| .pdata | 0x821CA800 | 0x0069ED0 | 0x40000040 |
| .text | 0x82240000 | 0x11C2474 | 0x60000020 |
| .data | 0x83410000 | 0x02339DC | 0xC0000040 |
| .tls | 0x83643A00 | 0x00005B5 | 0xC0000040 |
| .XBMOVIE | 0x83644000 | 0x000000C | 0xC0000040 |
| .idata | 0x83650000 | 0x00004F8 | 0xC0000040 |
| .XBLD | 0x83660000 | 0x0000130 | 0x42000040 |
| .reloc | 0x83660200 | 0x00E8EA8 | 0x42000040 |

- `.text` ≈ 17,8 МБ кода; `.pdata` 0x69ED0 байт → ~54 234 записей по 8 байт (оценка числа функций, не
  проверено).
- Не разобрано: `.idata` начинается на том же адресе, что и XEX-ресурс (0x83650000), а `.reloc` по
  виртуальному размеру выходит за image size. Скорее всего, у секций, отброшенных при сборке XEX, остался
  только заголовок, но это не проверено.

## Импорты

| Модуль | Версия (min) | Импортов |
|---|---|---|
| xam.xex | 2.0.21256.0 (2.0.16537.0) | 210 |
| xboxkrnl.exe | 2.0.21256.0 (2.0.16537.0) | 353 |

Источник: opt. `0x000103FF`. Других модулей в таблице импорта нет.

## Дополнительные .xex-модули

**Нет: `[[modules]]` в манифесте не нужен.** Игра импортирует `XexLoadImage`, но загружает через него только
системные модули.

1. На образе один исполняемый файл — `Default.xex` (полный список — [files.md](files.md)).
2. В таблице импорта только `xam.xex` и `xboxkrnl.exe`. Ординалы импортов разрешены по
   `sdk/src/kernel/xboxkrnl/export_table.inc`, результат — в `logs/xex_imports.log`. Среди них есть функции
   загрузки модулей:

   | Импорт | Ординал | Thunk |
   |---|---|---|
   | XexLoadImage | 0x199 | 0x83401F04 |
   | XexUnloadImage | 0x1A1 | 0x83401EF4 |
   | XexGetModuleHandle | 0x195 | 0x83401944 |
   | XexGetProcedureAddress | 0x197 | 0x83401934 |

3. Скан `.text` на `bl` к thunk'у `XexLoadImage` дал **один** вызов: 0x8299FEC8 внутри функции `0x8299FEB0`
   (0x44 байта по `.pdata`). Это обёртка в духе LoadLibrary. Других ссылок на неё нет, кроме её записи в `.pdata`
   (0x82203100). У обёртки два прямых вызывающих, и оба передают константное системное имя:
   - `0x829C1378` → r3 = 0x820759B8 `"xboxkrnl.exe"` (lis/addi на 0x829C1394);
   - `0x82C359E8` → r3 = 0x8202EE7C `"xam.xex"` (на 0x82C35A0C).
4. `XexGetModuleHandle`: 5 вызовов (0x826A4624, 0x826A4878, 0x82997754, 0x829A0380, 0x82C28020). У четырёх
   r3 = `"xam.xex"`, у вызова на 0x829A0380 аргумент не константа.
5. Во всех строках PE (ASCII, UTF-16LE/BE) единственное вхождение `.xex` — `xam.xex`; `.dll` нет.
6. `.xex`/`.xexp` внутри `$SystemUpdate/su20076000_00000000` — системное обновление дашборда (title
   `FFFE07D1`), к игре не относится.

Не проверено: аргумент `XexGetModuleHandle` на 0x829A0380 и вызов `XexGetProcedureAddress` на 0x8299FE58,
у которых имя не константа. Скан ловит только прямые `bl`, без косвенных вызовов через указатель на thunk.
Окончательно подтвердить можно в рантайме: залогировать `XexLoadImage_entry`
(`sdk/src/kernel/xboxkrnl/xboxkrnl_modules.cpp:86`).
