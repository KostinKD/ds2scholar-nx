# Рабочие рецепты (перенесены из ds2-nx, проверены там)

Перед командами: `$env:SA2_LLVM='G:\Program Files\LLVM'; $env:SA2_VSDIR='G:\Program Files\VisualStudio'`.

## Первая сборка в новом каталоге
- Проверка от 2026-11-03 и полные команды — [clean-build.md](clean-build.md).
  Фиксированные заголовки FFmpeg теперь подготавливает CMake из `ffmpeg-overlay`;
  копирование локальных заголовков из соседнего порта не требуется.
- Если отсутствуют исходники зависимостей, `python -I tools/fetch_thirdparty.py`
  загружает закреплённый upstream SDK с подмодулями. Вариант `--source <SDK>`
  использует локальную копию и копирует только отсутствующие файлы.
- Генератор: `cmake -S sdk -B out/host -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang
  -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_FLAGS=-march=x86-64-v2 -DCMAKE_CXX_FLAGS=-march=x86-64-v2
  -DREXGLUE_BUILD_TESTS=OFF`, `cmake --build out/host --target rexglue` → `sdk/out/win-amd64/rexglue.exe`.
- glslangValidator для шейдеров рендерера: `tools\win\build_glslang.ps1` (до PC-сборки, иначе «cannot find the path»).
- PC: `cmake --preset win-pc -S app`, затем `cmake --build out/pc --target ds2 -j 8` (первая полная ~35 мин при -j 8).
- Кодоген ~5 мин на прогон; этап 2 по шагам — docs/analysis/codegen.md.

## Пакет совместимости (DLC-каталог) — без него SotFS не стартует
- Распаковать `465307E4\00000002\D4B91B6B…` (`tools/stfs_extract.py <пакет> <папка>`) в
  `assets\content\0000000000000000\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646\` (внутри `Data\`).
- PC: junction `out\pc\userdata\0000000000000000\465307E4\00000002` → `assets\content\0000000000000000\465307E4\00000002`
  (`cmd /c mklink /J …`). Switch — путь на SD пока не выяснен.

## Сборка

Рекомендуемый вход для повторной PGO+LTO-сборки: `tools/win/rebuild_switch.ps1`.
Он ограничивает параллелизм 5 задачами, проверяет профиль и сохраняет полный лог;
подготовка и параметры — [rebuild.md](rebuild.md). Низкоуровневые команды ниже
остаются доступны для экспериментов.
- PC: `. tools\win\env.ps1; tools\win\run.ps1 logs\pc_build.log "cmake --build out/pc --target ds2"`.
- Switch: `tools\win\run.ps1 logs\build_nx.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\build_switch.ps1 -Jobs 5"`
  (полная ~1 ч; `-Jobs 8` падает по памяти cc1plus). Результат `out/nx/ds2.nro`, ELF `out/nx/ds2`.
- Проверка: `DEVKITPRO=G:/devkitPro python -I tools/check_switch_build.py --sdk-vulkan
  /g/DS2Switch/mesa-switch/builddir-unified/src/nouveau/vulkan/libvulkan.a [--reference-elf <ELF, проверенный на консоли>]`.
  Векторные FMA, которых нет в эталоне, — провал проверки.
- **Основная сборка — opt LTO + PGO** (с 2026-10-22, A/B в docs/progress.md): папка `out/nx_pgo`,
  `build_switch.ps1 -Jobs 5 -BuildDir out\nx_pgo -Define DS2_PGO=use,DS2_SWITCH_LTO=ON` (профиль — `pgo/`, не в git).
  Готовый профиль владельца v4 устанавливается отдельным пакетом **перед кодогеном**:
  [docs/pgo-profile.md](pgo-profile.md). В пакет входит `codegen.partition.json`:
  без него чистый кодоген распределяет функции иначе, и старые GCDA не подходят.
  Проверка применения с диагностикой: `python tools/pgo_fit.py --build-dir out/nx_pgo --all --jobs 5 --strict-guest`.
  Профиль заново (после кодогена или правок кода): `-Reconfigure -Define DS2_PGO=generate` → игра на консоли 5–10 мин →
  `ds2_pgo_<N>.stream` с FTP (`/switch/ds2scholar-nx/pgo`) → `tools\win\pgo_merge.ps1 <папка>` (старый `pgo/` убрать) →
  `-Reconfigure -Define DS2_PGO=use` (смена профиля без смены флагов — сначала `cmake --build out\nx_pgo --target
  clean`: ninja не следит за .gcda). Сессия не короче 2,5 мин (запись раз в 2 мин; при выходе через HOME файл не
  появлялся). Бэкап старого `pgo/` — не внутрь out\nx. Сессии хранить в `out/nx/keep/profiles/`. В generate-сборке GCC оставляет `b .`
  в гостевых остановках sub_82DFFE60 (`r9 -= r10` при r10 = 0, бесконечна и на Xbox) и sub_82E15628 (то же,
  `r11 -= r10` при r10 = 0; 2026-10-23): `--halts sub_82DFFE60,sub_82E15628`.
- Каждую сборку для консоли сохранять: `out/nx/keep/<имя>.nro` + `.elf` (профили читаются только с ELF той же сборки).
- Метка в hbmenu вместо пересборки: `python tools/nro_set_version.py <in.nro> <out.nro> <метка>`.
- Упаковка SD: `tools\win\package_switch.ps1` → `out\nx\sdcard\switch\ds2scholar-nx` (NRO, `ds2.toml`, пакет
  шейдеров). Игру владелец кладёт сам: `sdmc:/switch/ds2scholar-nx/game_root/`.
- Публичный ZIP с HOME: `package_switch.ps1 -Public -ForwarderDir <папка-проверенного-forwarder> -ReleaseDir <новая-папка>`.
  Проверяются NRO/NSP, добавляются RU/EN README, распаковщики, лицензии и SHA256SUMS.
  Игровые данные, ключи, сохранения и PGO не включаются. Подробности — [release-ready.md](release-ready.md).

## PC
- Тест до меню: `$env:REX_USER_DATA_ROOT='<repo>\out\pc\userdata'; $env:REX_DS2_INPUT_SCRIPT='28:start,50:a,58:a';
  $env:REX_DS2_SHOT_S='64'` + `tools\win\boot_test.ps1 -Exe out\pc\ds2.exe -Seconds 85`, снимки —
  `python tools/ppm_to_png.py out/pc/captures/*.ppm`. Тайминги скрипта — от DS2, для SotFS подобрать заново.
  SotFS (2026-10-21): титул «PRESS START» к ~85 с; до главного меню — `REX_DS2_INPUT_SCRIPT='88:start,105:a,118:a'`
  (Start, «No Ethernet cable» OK, «offline mode» OK), меню на снимке 135 с; `-Seconds 150`.
  Новая игра (чистый userdata + junction пакета): `88:start,105:a,118:a,128:a,134:a,140:a,146:a,152:a,158:a,164:a,175:start,178:a`
  → Междумирье с HUD к ~250 с (`-Seconds 270`); при наличии сейва меню позже (~140 с). Ходьба — `<с>:lsu:8000`.
  Снимки больше ~1 МБ PNG не открываются при просмотре — уменьшать до 960x540 JPEG (System.Drawing).
- A/B ключа рендерера: `tools\win\native_ab.ps1 -At 130 -Backup <сейв> -Script "28:start,50:a,..." -Runs "key=true|key=false"`
  → `out\pc\captures\ab_1.ppm`, `ab_2.ppm`, логи `out\pc\logs\ds2_NNN.log`. Несколько ключей в одном варианте —
  через `;`. Поворот камеры — `,90:rsr:38000`.
- Шум между одинаковыми прогонами (DS2, костёр): средняя разница 0.2–1.2/255, только пламя, экспозиция и плащ
  персонажа. Всё остальное — настоящее отличие.
- Покадровый лог резолвов: `sa2_diag_alias_frames=<кадр>` (40 кадров всех резолвов и их регистров).
  У костра Маджулы (сейв `out\gpu_lite2_pc_ab\baseline`, скрипт `88:start,105:a,118:a,145:a,152:a,162:a,205:b`)
  ~60 кадров/с: кадр 13300 ≈ 225 с.
- **Игру на PC не запускать через `tools/win/run.ps1`** (`native_ab.ps1`, `boot_test.ps1`): дважды повисла на
  ~203 КБ лога сразу после инициализации SDL (2026-10-25, ds2_096/098); тот же запуск напрямую с `*> logs\x.log` —
  нормально (ds2_103). Похоже на заполненный канал вывода.

## Консоль (как тестирует владелец)
- Владелец копирует NRO и `ds2.toml`, играет, копирует логи (`ds2_0NN.log`, `rex/rex_profile.log`,
  `rex/rex_stderr.log`) в свою папку и пишет «логи на месте». Новый прогон выбирать по первой метке времени внутри
  `ds2_*.log`, а не по времени файла (копируются разом).
- A/B: одна сборка, два конфига (`*_off.toml`/`*_on.toml`), **одно и то же место**, по ~1–2 мин стоя и с поворотами.
- Частоты владельца: CPU 1785 / GPU 921.6 / RAM 2133, портатив, OLED.
- Чтение логов:
  - fps и GPU по категориям — строки `GPU per Swap (N Swaps): total … scene … copies … edram_*` (N/10 = fps);
  - операции EDRAM — `mode4 operations since last report`; копии по адресам — `faces resolved since the previous report`;
  - долгие кадры — `[hitch] frame of X ms (GPU Y real …)`;
  - CPU по потокам — `rex_profile.log` (`^==== `, `-- thread N`); сравнение двух — `tools/ab_profile_compare.py`;
  - стеки: `switch_profile_stacks = true`, затем `tools/switch_profile_report.py <rex_profile.log> --elf <ELF>`.
- `rex_profile.log` перезаписывается каждым запуском — сразу копировать нужный в `out/nx/keep/profiles/`.

## Шейдеры
- Новые места: `sa2_shader_misses = "shader_misses"` → контейнеры в `shader_misses/missing/` на SD.
- Пакет: `tools/build_shader_library.sh <папки входов>` с `CXX="G:/Program Files/LLVM/bin/clang++.exe"` и
  `DXC=out/tools/dxc/bin/x64/dxc.exe`. Брать только шейдеры «not in the library» из хороших прогонов.

## Тяжёлые шейдеры по логу консоли
- `python -I tools/switch_shader_top.py out/switch_logs/latest/ds2_NNN.log [--top 25] [--from HH:MM:SS --to HH:MM:SS]` —
  пары VS/PS с наибольшим временем GPU (реальные мс, ×1,627), худшее 10-секундное окно и его время, хэш контейнера PS
  (код: `out/shaders/hlsl/ps_<хэш>.hlsl`). Нужен `sa2_gpu_marks_categories = true` (в `app/ds2_switch.toml` включён).
- Порядок работы (2026-10-23): владелец играет, говорит место и время провала; лог забирается по FTP, `--from/--to`
  сужают окно до провала.
