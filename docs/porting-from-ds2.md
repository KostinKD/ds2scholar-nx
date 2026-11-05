# Перенос из ds2-nx (обычная DS2, Xbox 360 TU0)

Репозиторий начат 2026-10-21 с ветки `codex` ds2-nx (коммит 87ed04ca) без истории. Здесь — что перенесено как есть,
что привязано к адресам DS2 и как переносить это на SotFS. История и доказательства по DS2 — `docs/ds2-nx/`

## Что переносится как есть
- `sdk/` — ReXGlue SDK с доработками порта: кодоген (локализация регистров, `non_volatile_as_local_keep`,
  `non_argument_as_local_keep`), Switch-слой (память, ввод с буквенной раскладкой, профайлер `switch_perf`,
  интервал показа кадра), сеть/XAM (заглушки и разведка онлайна `net_online_probe`), Vulkan-устройство
- `app/src/me/` — нативный рендерер (из sa2-nx): EDRAM mode 4, резолвы, импорты/экспорты глубины, метки GPU по
  категориям, ключи `ds2_*` рендерера (7e3, bias, claim, skip_repeated_depth_resolve). Логика от адресов игры не
  зависит, кроме хуков D3D (ниже)
- `shaders/` — XenosRecomp и сборка пакета шейдеров (`tools/build_shader_library.sh`); пакет шейдеров DS2 не
  переносится (собирать заново из `shader_misses/` SotFS; многие контейнеры могут совпасть — проверить)
- `tools/` — весь набор (анализ xex, gaps, pointers, switch_check, профили, A/B, сравнение снимков)
- конфиги `app/ds2.toml` (PC), `app/ds2_switch.toml` (Switch) — ключи рендерера и CPU; значения подобраны под DS2

## Что привязано к адресам DS2 TU0 (всё перепроверить)
Счётчик — строк с `0x82xxxxxx`/`sub_82xxxxxx` на 2026-10-21.

| Файл | Строк | Что | Как переносить |
|---|---|---|---|
| `app/overrides.toml` | 1090 | границы функций, switch-таблицы, setjmp/longjmp, noreturn, share_registers | заново этапом 2 (find_gaps, pointer_fixpoint, switch_check); из DS2 брать только как подсказку |
| `app/hot_functions.ld` | 2046 | порядок горячих функций для линкера | пересоздать по профилю SotFS (`tools/hot_order.py`); до этого `DS2_SWITCH_HOT_ORDER=OFF` |
| `app/perf_overrides.toml` | 57 | keep-списки локализации регистров, пост-шаги | очистить keep-списки, заново `tools/read_before_write.py` / `non_argument_audit.py` |
| `app/codegen_flavor.toml` | 57 | вариант кодогена | сверить адреса |
| `app/ds2_manifest.toml` | 3 | entry point, image size, путь к xex | из xex SotFS (этап 1) |
| `app/src/me/sa2_me_hooks.cpp` | 50 | хуки D3D рендерера | сопоставить с DS2 (ниже) |
| `app/src/ds2_me_hooks.cpp` | 31 | хуки D3D DS2 (Draw*, shader load, сбросы) | то же |
| `app/src/me/sa2_api_*.cpp/.h` | ~70 | адреса D3D-API | то же |
| `app/src/cpu/ds2_gpu_wait.cpp` | 14 | сон в ожидании GPU (`sub_829B9C60`) | сопоставить; хеш-проверка кода |
| `app/src/cpu/ds2_native_memcpy.cpp` | 12 | нативный memcpy XDK (`sub_82997E24`, ломался в GCC) | сопоставить; **важно** для шага 2 CPU |
| `app/src/me/me_native_system.*`, `me_ring_wait.cpp`, `sa2_d3d_api.cpp`, `ds2_d3d_census.cpp` | 3–5 | точечные адреса | сверить |
| `app/ds2_switch.toml` | 4 | адреса в ключах | сверить |
| `pgo/` | — | профиль DS2 удалён | снять заново (`-DDS2_PGO=generate` → сессия → `tools\win\pgo_merge.ps1`) |

Нативные замены в `app/src/cpu` включаются, только если хеш гостевого кода совпадает (`tools/guest_code_hash.py`):
на SotFS они не включатся, пока их не перепроверят, — это защита, а не ошибка.

## Как искать функции SotFS по DS2
У нас теперь есть эталон с названными функциями — сама DS2:
1. Распаковать обе игры (`tools/god_extract.py`), DS2 — во временную папку вне репозитория, SotFS — в `assets/game_root`.
2. Образ загруженной памяти: `SA2_DUMP_IMAGE` (см. `src/sa2_app.h`) для каждой игры; сгенерированное дерево DS2 —
   `G:\DS2Switch\ds2-nx\app\generated\default`.
3. `tools/d3d_match.py --ref-image <образ DS2> --ref-gen <generated DS2> --ref-names <toml с адресами DS2>` — ранжирует
   функции SotFS по форме инструкций (без непосредственных значений). Список имён DS2 — из
   `docs/ds2-nx/analysis/d3d.md` и хуков выше.
4. Каждое совпадение подтверждать как в DS2: вызывающие (`tools/d3d_find.py callers`), PM4-константы (`draws`),
   рантайм-счётчики (`ds2_d3d_census_s`). Записать в `docs/analysis/d3d.md` с доказательством.
5. Если XDK SotFS другой — смещения VS/PS в device (+0x3310/+0x330C у DS2) проверить заново.

## Уроки ds2-nx, которые экономят время
- Кодоген: «target not in any function» → find_gaps/gap_fixpoint до неподвижной точки; pointer_audit — диапазон кода
  берётся из `REX_CODE_BASE/SIZE` в `ds2_pch.h` (в SA2-инструментах был зашит свой).
- `sub_82997E24` (memcpy XDK с невыровненными векторами) GCC 16.1 портил при перестановке кода → нативный memcpy и
  `NO_BARRIER`/`tools/keep_volatile.py`. В SotFS искать тот же memcpy первым делом.
- Чёрное небо / шлейфы на эмулируемом GPU — `render_target_path_d3d12 = "rov"`.
- Онлайн: сеть заглушена, «No Ethernet cable» → offline; разведка локального сервера — `docs/ds2-nx/online.md`.
- На частотах владельца (CPU 1785 / GPU 921.6 / RAM 2133) упор в GPU: сцена 12–17 мс, копии 3.6 мс, резолвы ~3 мс;
  копии упираются в полосу памяти. Это главный довод за deko3d (docs/deko3d.md).
- Плохая/хорошая картинка на консоли: число «unidentified pixel shader» в логе (норма 0–3, сломанная сборка 23–48).
- Ограничение 30 fps (`ds2_frame_cap_30`, L+R+Минус) и буквенная раскладка (`input_xbox_layout = false`) — владелец
  хочет и здесь.
- 1080p сломан, 540 — двоение (дробный масштаб рендерера не доделан).
