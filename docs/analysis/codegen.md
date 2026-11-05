# Трансляция SotFS (этап 2)

Манифест — `app/ds2_manifest.toml` (проект `ds2`, без `[[modules]]`, entry 0x829C3DE0, image size 0x16F0000; см.
[xex.md](xex.md)). Ручные правки — `app/overrides.toml` (функции) и `app/switch_tables.toml` (таблицы переходов),
у каждой записи доказательство. Кодоген — `tools/codegen.ps1` (classic), логи прогонов — `logs/codegen_run*_full.log`.
Методика и шаблоны — те же, что у DS2 ([docs/ds2-nx/analysis/codegen.md](../ds2-nx/analysis/codegen.md)); здесь —
только факты SotFS. Дизассемблер — `tools/ppc_mini.py`, образ — `out/default_image.bin` (`REXGLUE_DUMP_IMAGE`).

## Генератор и окружение

- `cmake -S sdk -B out/host -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C/CXX_COMPILER=clang(++) -DCMAKE_C/CXX_FLAGS=-march=x86-64-v2
  -DREXGLUE_BUILD_TESTS=OFF`, `cmake --build out/host --target rexglue` → `sdk/out/win-amd64/rexglue.exe`.
- Первая сборка упала: в `sdk/thirdparty` не было 71 файла, которых нет в git-дереве ds2-nx (FFmpeg `config.h`,
  `libavutil/avconfig.h` и др.). Дозаполнено без сети: `python -I tools/fetch_thirdparty.py --source G:/DS2Switch/ds2-nx/sdk`
  (копирует только отсутствующие файлы; `logs/fetch_thirdparty.log`).
- Вариант кодогена — **classic**: `app/codegen_flavor.toml` пустой (в репозитории лежал optimised из ds2-nx, а
  `perf_overrides.toml` с адресами DS2).

## setjmp / longjmp

Найдены маскированной сигнатурой диапазонов DS2 (по одному совпадению):

| | SotFS | DS2 | Форма | Прямых вызовов |
|---|---|---|---|---|
| setjmp | 0x82FED7E0 (178 слов) | 0x82FB8A30 | `lis r4,0x8367; lwz r0,0x4C98(r4)` (хук 0x83674C98; у DS2 0x836439D8), `bnectr`, `mflr`… | 70 (DS2 68) |
| longjmp | 0x82FEC680 (`.pdata`, 0x314) | 0x82FB78D0 | та же | 430 (DS2 430) |

## Прогоны кодогена

| Прогон | Результат | Что сделано |
|---|---|---|
| 1 | 50 «target not in any function» | 50 записей `{ }` (`tools/unresolved_calls.py`): 18 thunk `lwz r3,8(r3); b` (таблица 0x823A47xx), 23 хвостовых вызова, 9 фрагментов; ни одна цель не внутри `.pdata` |
| 2 | 1 | ещё thunk той же таблицы 0x823A4BF8 (как у DS2) |
| 3 | 0, но 8 «Unresolved conditional branch» | два листа без `.pdata` целиком: 0x828EF5D8 `size 0xA4` (= лист DS2 0x828BF378, указатель 0x8205052C) и 0x82FADE98 `size 0xB0` (хвост thunk'а `sub_82FADDF8`, генератор вставил его за концом функции) |
| 4 | 0 / 0 `REX_FATAL` | — |
| 5 | pointer_fixpoint: проход 1 — 267 кандидатов, 248 приняты; проход 2 — новых нет. Но кодоген: «Jump target … unresolved» на `bctr` 0x828F38DC/0x828F3928 | приняты 5 целей **строго внутри функций с `.pdata`**: базы трёх абсолютных `switch`-таблиц в `sub_828F36A0` и одной в `sub_828F2D20`, и маркер SEH `mr r8,r8` 0x829D37D4 (запись области {0x829D37D4, 0x829D386C, …} по 0x821CD958; у DS2 то же — 0x829A3604). Удалены; `pointer_fixpoint.py` теперь отбрасывает такие кандидаты (как `gap_fixpoint.py`) |
| 6 | 0 / 0, 83 834 функции | — |
| 7 | pointer_audit: 5 vtable-like | 5 разрезанных листьев по 0xD8 (0x82646FB0, 0x82647360, 0x82647718, 0x82647E20, 0x82648200; указатели в таблицах 0x8202AA80…0x8202AC64) целиком, их фрагменты прогона 1 удалены. Границы — `tools/leaf_walk.py` (`logs/leaf_walk_vtable5.log`) |
| 8 | 0 / 0 | компаратор `qsort` 0x82B33340 `size 0x88` (передаётся в CRT `qsort` 0x82FF21E8 как r6; gap fill разрезал его на 0x82B333B4). У DS2 тот же компаратор (0x82B03D30) остался незарегистрированным |
| 9 | switch_check: 2 неверные таблицы | `app/switch_tables.toml`: две таблицы полуслов в `sub_825EFDF0` (`bctr` 0x825F0AE8 — 13 случаев, 0x825F14AC — 24) вместо 1024 неверных; метки пересчитаны вручную |
| gap_fixpoint | проходы 1–5: 649 → 99 → 55 → 8 → 0 принятых | итог ниже |

## Итог (после gap_fixpoint)

- **0 «Unresolved», 0 `REX_FATAL`**, 84 532 функции в сгенерированном коде (84 811 зарегистрированных по
  pointer_audit), 1108 записей в `overrides.toml` (DS2: 83 841 / 1104); ни одна запись не лежит внутри
  `.pdata`-функции.
- `switch_check` (`logs/switch_check3.log`): `bctr` — 1587 косвенных, 183 byte-, 77 half-, 530 absolute-таблиц;
  сгенерировано 787 switch и 1595 косвенных. Усечённых 0, неверных 0, пропущенных 0, «extra» 2.
  «No bound in the code» 31: 27 абсолютных таблиц сразу за `bctr` — число записей до первого слова, которое не
  адрес кода, совпадает с числом случаев во всех 27; две таблицы полуслов (17 и 16 — те же, что у DS2); байтовая
  таблица `sub_825CA958` (16 смещений, кратных 4; 17-е = 9 уже не годится); вызов через таблицу указателей с
  проверкой на NULL `sub_8271E790` (косвенный). Odd shapes 5 — не разбирались поштучно.
- `pointer_audit` (`logs/pointer_audit_final.log`): vtable-like **0**, built in code 14 (базы `switch` и адреса
  продолжения после `bctr`/вызова; единственная цель в промежутке — 0x82FEDCC8, адрес возобновления SEH-фанклета,
  как 0x82FB8F18 у DS2).

## Инструменты, поправленные под SotFS

- `gap_fixpoint.py`: `.pdata` из таблицы секций образа (было зашито 0x821CA800/0x69ED0 DS2); пробный манифест
  включает `switch_tables.toml`.
- `pointer_fixpoint.py`: отбрасывает кандидатов внутри `.pdata`-функций; пробный манифест включает `switch_tables.toml`.
- `d3d_find.py`, `pointer_scan.py`: конец `.text` SotFS 0x83438264.
- Новые: `tools/unresolved_calls.py` (записи для «target not in any function» с классификацией),
  `tools/leaf_walk.py` (границы разрезанного листа обходом переходов).

## Не проверено

- Сборка и запуск сгенерированного кода (этап 3).
- noreturn-аудит (`read_before_write.py --noreturn=`) — нужен только для optimised-варианта; не запускался.
- 4 фрагмента прогона 1 (0x8284B85C, 0x828D88F4, 0x828D8A0C, 0x82CFF064) оставлены как у DS2 (корректны в classic).
- Записи gap-скана вне `.pdata` проверены только автоматикой (classify + отсутствие «Unresolved»).
- 8 функций дают больше 1 МБ C++ (0x825EFDF0, 0x82D73190, 0x82D81008, 0x82D8EE80, 0x82D9C900, 0x82DA98A8, 0x82DB6808, 0x82DC47C0) — только предупреждение генератора.
