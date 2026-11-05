# Если готовый игровой ZIP недоступен: собрать пакет самому

Обычная установка использует готовый ZIP из Releases. Этот раздел — запасной
путь для сборки **своего** `ds2.nro` и архива с папкой `switch/`.
Игровые файлы и ключи в итоговый публичный ZIP не включаются.

Нужны три компонента: **NRO + пара файлов шейдеров + конфиг**. Один NRO не заменяет
готовый игровой пакет. NSP для плитки HOME необязателен: можно запускать NRO
через hbmenu в режиме title override.

**Ограничение:** это не автоматическая установка SDK на чистый ПК. Сначала нужны
Windows-инструменты и совместимая Mesa/NVK с патчами из
[описания среды](clean-build.md). Такая Mesa/NVK в репозиторий не входит.
Базовая библиотека шейдеров из своей игры также не гарантирует побайтового
совпадения с релизом или покрытия всех вариантов, встречающихся во время игры.

## 1. Подготовить исходники и свою игру

Клонируйте репозиторий через Git и распакуйте свою Xbox 360 SotFS в
`assets/game_root/`; должен существовать `assets/game_root/default.xex`.
Compatibility Pack 4 нужен для запуска игры на Switch, но в ZIP порта не добавляется.

```powershell
git clone -c core.autocrlf=false https://github.com/KostinKD/ds2scholar-nx.git
cd ds2scholar-nx
python tools/god_extract.py "<полный путь к заголовку GoD>" -o assets/game_root
```

Перед следующими командами настройте `SA2_LLVM`, `SA2_VSDIR`, `DEVKITPRO`
и `NVK_SDK` на свои каталоги по [инструкции среды](clean-build.md).
Настройка `core.autocrlf=false` сохраняет Bash-скрипты с LF-переносами строк.

## 2. Получить NRO

Если доступен отдельный PGO ZIP, установите его **до кодогена** по
[инструкции PGO](pgo-profile.md), затем выполните:

```powershell
tools/win/rebuild_switch.ps1
```

**Результат: `out/nx_pgo/ds2.nro`**. Скрипт сам собирает host-инструменты,
генерирует код и компилирует NRO с PGO + LTO.

Если PGO ZIP тоже недоступен, можно собрать **без PGO**. Это отдельная
конфигурация; прежний FPS не обещается. В новой подготовленной копии выполните:

```powershell
tools/win/run.ps1 logs/host_configure.log "cmake -S sdk -B out/host -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_FLAGS=-march=x86-64-v2 -DCMAKE_CXX_FLAGS=-march=x86-64-v2 -DREXGLUE_BUILD_TESTS=OFF"
tools/win/run.ps1 logs/host_build.log "cmake --build out/host --target rexglue -j 5"
tools/win/run.ps1 logs/glslang.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_glslang.ps1"
tools/win/run.ps1 logs/codegen.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/codegen.ps1 -Flavor optimised"
tools/win/run.ps1 logs/nro_no_pgo.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_switch.ps1 -Jobs 5 -BuildDir out/nx_no_pgo -Define DS2_SWITCH_LTO=ON"
```

**Результат без PGO: `out/nx_no_pgo/ds2.nro`**. Далее подставляйте этот путь
в `-Nro` вместо `out/nx_pgo/ds2.nro`. Отдельный каталог сборки нужен, чтобы
не использовать прежние флаги PGO из CMake-кеша.

## 3. Подготовить оба файла шейдеров

Нужны **`sa2_shaders.mesp` и `sa2_shaders.mesp.idx` из одного набора**.

Если у вас осталась собственная рабочая установка, можно взять эту пару из
`SD:/switch/ds2scholar-nx/` в отдельную папку, например `out/my-shaders/`,
и использовать её как `-ShaderDir` на следующем шаге.

Если пары нет, базовую библиотеку можно собрать из своей распакованной игры.
Дополнительно нужны **MSYS2 Bash**, LLVM/Clang и **DXC с поддержкой SPIR-V**.
DXC из произвольного Windows SDK не следует считать подходящим автоматически.

Сначала извлеките контейнеры из `assets/game_root/shader/*.bnd`:

```powershell
tools/win/run.ps1 logs/shader_inputs.log "python -I tools/bnd_shader_inputs.py -o out/shader_inputs/sotfs_bnd"
```

Затем укажите свои пути к Bash и DXC. Команды выполняются из корня клона:

```powershell
$env:DS2_BASH = 'C:/msys64/usr/bin/bash.exe'
$env:DXC = 'C:/Tools/dxc/bin/x64/dxc.exe'
tools/win/run.ps1 logs/shader_build.log "`"$env:DS2_BASH`" tools/build_shader_library.sh out/shader_inputs/sotfs_bnd"
```

**Результат: `out/shaders/sa2_shaders.mesp` и `.mesp.idx`.** Скрипт пересоздаёт
свой каталог `out/shaders/`; не храните там единственный экземпляр рабочего набора.
Проверьте `out/shaders/translate_failed.txt` и файлы `out/shaders/spirv/*.err`:
ошибки перевода/компиляции нельзя считать готовой библиотекой только по коду выхода.

Варианты вершинных шейдеров, которые игра меняет во время выполнения, не все
содержатся в BND. При недостающих шейдерах/неправильной картинке нужны свои
runtime-дампы из `shader_misses/missing/` и `shader_misses/variants/` при
`sa2_shader_misses = "shader_misses"`. Дополнительные каталоги `.bin` передаются
в тот же `build_shader_library.sh` после каталога BND. Это сборка и проверка
своего набора, а не обещание точной копии проверенного релизного пакета.
Оптимизированный набор релиза `shader_light2_v2` нельзя восстановить одним
копированием файлов из Git — там его нет. Пересборка всей этой цепочки
на новой машине в текущей сессии не проверялась.

## 4. Упаковать ZIP без NSP и без ключей

Для NRO из шага 2 и пары шейдеров из `out/shaders/`:

```powershell
tools/win/run.ps1 logs/package_zip.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/package_switch.ps1 -Public -Nro out/nx_pgo/ds2.nro -ShaderDir out/shaders -ReleaseDir out/release/my-player-package"
```

**Результат: `out/release/my-player-package.zip`.** Появится и одноимённая
распакованная папка. Для повторной упаковки выбирайте новый `-ReleaseDir`:
существующие результаты не перезаписываются.

В архив автоматически попадут NRO, публичный `ds2.toml`, пара шейдеров,
распаковщики игры, инструкция, лицензии и контрольные суммы.
**В этом варианте NSP не включён.** Скопируйте `switch/` на SD, добавьте свою
игру и Compatibility Pack 4, затем запускайте `ds2.nro` через hbmenu:
удерживайте **R при старте установленной игры**, чтобы получить title override.
В режиме Album недостаточно памяти. Внутри ZIP будет инструкция именно для этого способа.

Упаковка не создаёт отсутствующие NRO или шейдеры и не проверяет все игровые сцены.
После неё необходим собственный запуск на Switch.

## 5. Необязательно: добавить плитку HOME

Для своего NSP нужны дополнительные инструменты и **свой локальный `prod.keys`**.
Ключи не добавляются в ZIP или Git. Подготовка среды:
[сборка HOME-forwarder](forwarder.md#сборка-на-windows).

```powershell
$env:SWITCH_PROD_KEYS = 'C:/private/prod.keys'
tools/win/run.ps1 logs/forwarder_build.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_forwarder.ps1 -Nro out/nx_pgo/ds2.nro -Output out/my-forwarder"
tools/win/run.ps1 logs/package_home_zip.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/package_switch.ps1 -Public -Nro out/nx_pgo/ds2.nro -ShaderDir out/shaders -ForwarderDir out/my-forwarder -ReleaseDir out/release/my-home-package"
```

**Результат: `out/release/my-home-package.zip`** с NSP и инструкцией DBI → HOME.
NSP собирается для того же NRO; упаковщик проверяет их соответствие.
Если NRO пересобран, пересоберите forwarder перед упаковкой.

---

## English summary

If the prebuilt player ZIP is unavailable, the five stages above are:

1. Clone the repository and extract your own Xbox 360 SotFS to `assets/game_root/`.
   Prepare Windows build tools and the external patched Mesa/NVK SDK first.
2. Install the optional PGO bundle and run `tools/win/rebuild_switch.ps1` to get
   **`out/nx_pgo/ds2.nro`**. Without a PGO bundle, use the explicit host/codegen/
   non-PGO build commands in section 2; output is **`out/nx_no_pgo/ds2.nro`**.
3. Supply both matching shader-library files. Reuse your own working installation,
   or extract BND shader containers and compile with the commands in section 3.
   The basic BND library may need runtime vertex variants; it is not a verified
   byte-identical reproduction of the release library.
4. Run the section 4 packaging command, changing `-Nro` and `-ShaderDir` to your
   actual outputs. Result: **`out/release/my-player-package.zip`**. No NSP or keys
   are required; launch the NRO from hbmenu using **R + an installed game**.
5. Optionally build your own forwarder with your local keys and use `-ForwarderDir`
   as shown in section 5. Result: **`out/release/my-home-package.zip`**.

Packaging includes config, extractors, licenses and checksums; it excludes game
data and keys. Never overwrite the only copy of your shader inputs. A complete
fresh-machine SDK/shader rebuild has not been validated here; packaging alone
does not prove runtime correctness. Test your own result on Switch.
