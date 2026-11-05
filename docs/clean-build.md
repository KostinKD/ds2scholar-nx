# Проверка сборки из чистого клона — 2026-11-03

База проверки: `6569c5aeb2f161eafccd2ac2ccc12dce0acec090`, отдельный
`git clone --no-hardlinks --no-local . out/clean-clone-20261103`.
Готовые `out/`, `sdk/out/`, `app/generated/` и PGO-профиль не переносились.
Игра подключена junction `assets/game_root` к существующей распакованной
копии владельца; игровые данные используются только как вход кодогена.

Это проверка чистого дерева проекта на подготовленной Windows-машине,
а не установка инструментов на чистую ОС. Внешние LLVM, Visual Studio,
devkitPro и Mesa/NVK остаются предварительными зависимостями.
Зафиксированы devkitA64 GCC 16.1.0 и Mesa checkout
`1a8c1a66d6fd8d65f10107c4627ffc3606ba5631` с локальными патчами.
Используемый `mesa-unified-install/opt/devkitpro/portlibs/switch/lib/libvulkan.a`:
93 439 442 байта, SHA256
`EB32061AA4FE48D5427B95D14AAE60C1928AC23211B0932AFD3AF141E25EA9BA`.
Один только commit Mesa не воспроизводит эту библиотеку без её патчей.

## Найденный блокер

Первая host-сборка остановилась на первом из 770 шагов: отсутствовали
`FFmpeg/config.h` и `FFmpeg/libavutil/avconfig.h`. Также в Git отсутствует
`FFmpeg/libavutil/ffversion.h`. Эти заголовки есть в рабочей копии, но
игнорируются правилами FFmpeg; платформенные конфиги при этом отслеживаются.
Старый рецепт копирования зависимостей из соседнего `ds2-nx` скрывал проблему.

Исправление: три фиксированных заголовка хранятся в `ffmpeg-overlay`,
CMake копирует их в каталог сборки и добавляет его к include-путям FFmpeg.
Параметры совпадают с прежними рабочими заголовками: little-endian,
fast unaligned, версия `xenia-premake`, выбор существующего конфига платформы.
Игровой код и настройки рендерера не меняются.

## Последовательность

Из корня клона, со своими путями инструментов:

```powershell
$env:SA2_LLVM = 'G:\Program Files\LLVM'
$env:SA2_VSDIR = 'G:\Program Files\VisualStudio'
$env:DEVKITPRO = 'G:/devkitPro'

tools/win/run.ps1 logs/host_configure.log "cmake -S sdk -B out/host -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_FLAGS=-march=x86-64-v2 -DCMAKE_CXX_FLAGS=-march=x86-64-v2 -DREXGLUE_BUILD_TESTS=OFF"
tools/win/run.ps1 logs/host_build.log "cmake --build out/host --target rexglue -j 5"
tools/win/run.ps1 logs/glslang.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_glslang.ps1"

# До следующей команды подготовить свою игру в assets/game_root.
tools/win/run.ps1 logs/codegen_optimised.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/codegen.ps1 -Flavor optimised"
tools/win/run.ps1 logs/switch_build.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_switch.ps1 -Jobs 5"
tools/win/run.ps1 logs/switch_check.log "python -I tools/check_switch_build.py --sdk-vulkan G:/DS2Switch/mesa-switch/mesa-unified-install/opt/devkitpro/portlibs/switch/lib/libvulkan.a"
```

Для другого размещения devkitPro/Mesa передать `DEVKITPRO` и `NVK_SDK`;
подробности — в `tools/win/build_switch.ps1`. PGO для этой проверки выключен:
его профиль собирается отдельно на консоли, см. [workflow.md](workflow.md).

`tools/fetch_thirdparty.py` не потребовался для компиляции этого клона:
нужные исходники уже отслеживаются в Git. Проверочный запуск загрузчика
получил закреплённый SDK, но полная рекурсивная загрузка подмодулей была
остановлена на SDL3 до стадии копирования файлов в проект. Успешное
завершение сетевого загрузчика здесь не подтверждено; его нельзя считать
проверенным способом восстановления локальных конфигурационных заголовков.
Лог попытки — `logs/fetch_thirdparty_network.log`, exit 1 после остановки.

## Результаты

- Клонирование: exit 0, 20 310 файлов.
- Host configure: exit 0, Clang 20.1.8.
- Host build до исправления: exit 1, отсутствуют заголовки FFmpeg.
- Host build с overlay: exit 0, получен новый `sdk/out/win-amd64/rexglue.exe`.
- glslangValidator: 57/57 шагов, exit 0.
- Optimised-кодоген: exit 0, основной проход 328,6 с, 659 записанных файлов;
  постобработка: 37 347 барьеров циклов, 223 605 прямых вызовов,
  без `Unresolved` и `REX_FATAL` в логе генератора.
- Switch-сборка: 957/957 шагов, exit 0, 19:01:29–19:31:00 (29 мин 31 с).
  `Release`, optimised, LTO включён (2 процесса), `-Jobs 5`, PGO выключен.
- `check_switch_build.py`: exit 0, все проверки пройдены без дополнительных
  исключений: `_start = 0`, строка Mesa 26.2.1 совпадает с SDK,
  одна известная гостевая остановка, 10 614 scalar FMA и 6 vector FMA
  в одной функции (8 допустимых в штатном списке).

В конце LTO GCC сообщил два `-Wstringop-overflow` в
`VertexFetchReorderAgreesWithPlacements` при встраивании `std::next_permutation`.
Они не остановили сборку. Причина предупреждений отдельно не исследовалась;
код рендерера в этой проверке не менялся.

Артефакты в `out/clean-clone-20261103/out/nx/`:

| Файл | Байт | SHA256 |
|---|---:|---|
| `ds2.nro` | 89 139 397 | `91DB0A8119087CF5BC3D1B297851A62A8D265B6BB0E8EEFCA276D1CA1012181E` |
| `ds2` (ELF) | 110 672 648 | `B9424EA5C21763CA82FC619913B22006437210004B62C86E176A1CD119764B21` |

Полные логи находятся в ignored-каталоге
`out/clean-clone-20261103/logs/`; внутренние логи glslang и кодогена — в
`out/clean-clone-20261103/out/`. Изменение overlay перенесено в клон отдельно;
результаты исходного коммита и изменённых исходников различаются выше.
Четыре изменённых входа сборки (CMake и три заголовка) сверены между клоном
и рабочей веткой: отличий с учётом CRLF нет,
`logs/clean_changed_inputs_20261103.log`, exit 0. Содержательных изменений
других отслеживаемых исходников в клоне нет (`git diff --numstat`).

Здесь не проверяются релизный ZIP, запуск на консоли, PGO, полная PC-сборка
и самостоятельная пересборка внешнего Mesa/NVK.
