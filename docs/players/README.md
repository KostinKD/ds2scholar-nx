# DS2 SotFS — Switch player guide / Инструкция игрока

[English](#english) · [Русский](#русский)

## English

Unofficial homebrew port of **Xbox 360** Dark Souls II: Scholar of the First Sin,
using ReXGlue and Vulkan/NVK, with online play on the project's server.

### Requirements

- Switch with Atmosphère, hbmenu and DBI; about **8 GB** free on SD.
- Your own Xbox 360 Games on Demand copy and **Compatibility Pack 4**.
  The pack is required to start the game. PC, PS3 and later console versions
  cannot be used as input for this port.
- PC with **Python 3.10+** for extraction.

The prepared package contains NRO `1.10.0-access1`, `ds2.toml`,
`sa2_shaders.mesp`, `sa2_shaders.mesp.idx` and `ds2scholar-forwarder.nsp`
in `switch/ds2scholar-nx/`, with `extract-tools` and licenses at the ZIP root.
Game files, keys and saves are not included. A source checkout is not a ready-to-play package.

### Install

1. Copy the package's `switch` folder to the SD root.
2. From the extracted package directory, unpack your game (about 6 GB):

   ```powershell
   python extract-tools/god_extract.py "<your files>\465307E4\00007000\<game file>" -o "<SD>\switch\ds2scholar-nx\game_root"
   ```

   Keep `<game file>.data` beside the GoD header during extraction.
3. Unpack your Compatibility Pack 4 (about 1.2 GB):

   ```powershell
   python extract-tools/stfs_extract.py "<your files>\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646" "<SD>\switch\ds2scholar-nx\ds2\0000000000000000\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646"
   ```

4. Install `switch/ds2scholar-nx/ds2scholar-forwarder.nsp` with **DBI**.
5. Start the **DS2** tile from HOME. Choose the **same Switch user** as before:
   saves and online identity depend on that user.

Keep `sdmc:/switch/ds2scholar-nx/ds2.nro` and the entire game folder on SD:
the NSP launches that NRO. HOME launch, saves and the selected cover have been
confirmed on the owner's console. If an old icon remains after reinstalling
the NSP, fully restart the console/Atmosphère. Copying the NSP to SD alone
does not update an installed tile.

The forwarder requests a 39-bit address space and cores **0–3**. The console log
confirmed process mask `0xF`; a speedup from the fourth core has not been measured.
Alternative: hold **R** while starting an installed game to open hbmenu
(title override), then start the port. Fourth-core access depends on the loader.
Album applet mode does not provide enough memory.

### Updates and controls

Keep `game_root/` and **`ds2/`**, which contains saves and the compatibility pack.
Back up your existing `ds2.toml`, compare it with the new supplied config and
carry over the settings you need. Install an updated NSP over the existing one
through DBI. Continue choosing the same Switch user.

Buttons follow **Switch letters**: A confirms, B cancels/rolls
(`input_xbox_layout = false`). Other settings are in `ds2.toml`.

### Maximum FPS

For the highest frame rate, start the supplied PGO+LTO build from the **DS2 HOME
tile** and use the recommended maximum-FPS profile: **FSR 1 + fixed 540p +
the 30 fps cap disabled** in handheld mode.
This trades image sharpness and even frame pacing for higher frame rates.

| Shortcut | Action |
|---|---|
| L + R + Minus | Toggle the 30 fps cap |
| L + R + Plus | Toggle dynamic resolution |
| L + R + right-stick click | Cycle dynamic / fixed 720p / fixed 540p |
| L + R + left-stick click | Cycle the upscaler — select FSR 1 |

1. Back up `sdmc:/switch/ds2scholar-nx/ds2.toml` and close the game.
2. Edit the existing keys below, adding the render-height key if absent. Keep
   the remaining supplied optimizations enabled; avoid duplicate TOML keys.

   ```toml
   present_effect = "fsr"
   ds2_frame_cap_30 = false
   ds2_dynamic_resolution = false
   sa2_render_height_handheld = 540
   ds2_vpos_render_scale = true
   ```

3. Start the game again. Check the on-screen notification for the selected mode.
   The config above selects FSR 1 and 540p on the next launch.

For a steadier **30 fps** presentation, keep the supplied settings instead:
`ds2_frame_cap_30 = true`, `ds2_dynamic_resolution = true`, and the default
handheld render height of 720. Dynamic resolution can then drop to 540p under load.
If you added the fixed-540p line, remove it or change it to 720 before using this preset.

**Clock conditions matter.** The main tests used a handheld **Switch OLED** at
**CPU 1785 / GPU 921.6 / RAM 2133 MHz**, configured externally. The port does
not install an overclocking setup or automatically apply these three frequencies.
If you already use a compatible clock manager, apply the profile to the forwarder
title **`01445332534F0000`** and check the actual clocks after opening HOME.
These are measured conditions for that console, not a universal maximum or a
validated profile for every Switch model. Use frequencies supported by your setup.

Historical uncapped measurements at those clocks in a static Majula bonfire scene
were about **33 fps at 720p** and **40 fps at 540p**; a CPU-bound Heide's Tower
test was about **32 fps**. These were earlier optimization builds, not a new
benchmark of `1.10.0-access1`. Lower resolution helps GPU-bound scenes; it does
not remove CPU or streaming stalls. Stable 60 fps has not been demonstrated.
The forwarder exposes cores 0–3, but its FPS gain has not been measured.

Keep the bundled FSR/FXAA settings as the tested image-quality baseline.
Their individual FPS cost has not been established, so disabling them is not
presented as a measured improvement. The separate PGO ZIP is for developers;
the player NRO already contains the build optimizations.

### Online

The supplied config uses **`ds2scholar.download`** with server relay enabled;
no router port forwarding is needed. Availability depends on the project server.
Messages, ratings, bloodstains, ghosts, summon signs and player names have been
tested. Switch/PC summons and invasions passed tests on 29 October 2026;
after the reconnect fix, world entry in both directions was confirmed again
on **1 November**.

Your online identity follows your Switch user. Your nickname is transliterated
from Cyrillic; unsupported names fall back to `Player-XXXX`. Override it with
`net_profile_name = "YourName"` in `ds2.toml`: Latin letters, digits, spaces and
`_ - .`, up to 15 characters. When migrating to user-based identity, older saves
are copied once; the original folder remains.

The console-key server gate (`access1`) has not completed end-to-end validation;
the NRO version label alone does not confirm that feature.

### Limits and help

- Target: 30 fps, dynamic 720p/540p, FSR 1 and FXAA. Main measurements used
  handheld Switch OLED at CPU 1785 / GPU 921.6 / RAM 2133 MHz. Heavy scenes and
  loading can drop frames; stock-clock performance is not promised. TV mode has less coverage.
- A full playthrough, all DLC areas, 3–4-player co-op and network recovery after
  sleep have not been fully tested.
- A PC null-address crash after returning from a summon remains unresolved;
  the same crash has not been confirmed on Switch.
- If repeated multiplayer disconnects trigger a Bone of Order warning, use that
  item on the affected character. Server settings do not remove this game restriction.
- Lighting flicker/a black square was observed in a corner of McDuff's workshop.

Logs: `sdmc:/switch/ds2scholar-nx/logs/ds2_NNN.log` (largest number is newest).
Include the latest log, version, location, steps and handheld/TV mode in a bug report.

The separate **PGO ZIP is optional and only needed for rebuilding**, not playing:
[PGO instructions](../pgo-profile.md), [rebuild instructions](../rebuild.md).
When extracting from a source checkout, use `tools/` instead of `extract-tools/`.

## Русский

Неофициальный homebrew-порт **Xbox 360** Dark Souls II: Scholar of the First Sin
через ReXGlue и Vulkan/NVK, с онлайном на сервере проекта.

### Что нужно

- Switch с Atmosphère, hbmenu и DBI; около **8 ГБ** свободного места на SD.
- Своя Xbox 360 копия в формате Games on Demand и **Compatibility Pack 4**.
  Без пакета игра не запускается. Версии для PC, PS3 и более поздних консолей
  не подходят в качестве входных данных этого порта.
- PC с **Python 3.10+** для распаковки.

Подготовленный пакет содержит NRO `1.10.0-access1`, `ds2.toml`,
`sa2_shaders.mesp`, `sa2_shaders.mesp.idx` и `ds2scholar-forwarder.nsp`
в `switch/ds2scholar-nx/`, а также `extract-tools` и лицензии в корне ZIP.
Файлов игры, ключей и сохранений в нём нет. Клон исходников сам по себе
не является готовым игровым пакетом.

### Установка

1. Скопируйте папку `switch` из пакета в корень SD.
2. Из каталога распакованного пакета распакуйте свою игру (около 6 ГБ):

   ```powershell
   python extract-tools/god_extract.py "<ваши файлы>\465307E4\00007000\<файл игры>" -o "<SD>\switch\ds2scholar-nx\game_root"
   ```

   Во время распаковки папка `<файл игры>.data` должна лежать рядом с заголовком GoD.
3. Распакуйте свой Compatibility Pack 4 (около 1,2 ГБ):

   ```powershell
   python extract-tools/stfs_extract.py "<ваши файлы>\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646" "<SD>\switch\ds2scholar-nx\ds2\0000000000000000\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646"
   ```

4. Установите `switch/ds2scholar-nx/ds2scholar-forwarder.nsp` через **DBI**.
5. Запустите плитку **DS2** из HOME. Выберите **того же пользователя Switch**,
   которым играли раньше: от него зависят сохранения и онлайн-личность.

Оставьте `sdmc:/switch/ds2scholar-nx/ds2.nro` и всю папку игры на SD:
NSP запускает этот NRO. Запуск с HOME, сохранения и выбранная обложка подтверждены
на консоли владельца. Если после переустановки NSP осталась старая иконка,
полностью перезапустите консоль/Atmosphère. Одного копирования NSP на SD
для обновления установленной плитки недостаточно.

Forwarder запрашивает 39-bit адресное пространство и ядра **0–3**. Лог консоли
подтвердил маску процесса `0xF`; прирост FPS от четвёртого ядра не измерен.
Альтернатива: запустите установленную игру с зажатой **R**, чтобы открыть hbmenu
(title override), затем запустите порт. Доступ к четвёртому ядру зависит от
загрузчика. В режиме Album недостаточно памяти.

### Обновления и управление

Сохраняйте `game_root/` и **`ds2/`**: в `ds2/` находятся сохранения и пакет
совместимости. Сделайте резервную копию своего `ds2.toml`, сравните с новым
конфигом и перенесите нужные параметры. Обновлённый NSP устанавливайте через DBI
поверх прежнего. Продолжайте выбирать того же пользователя Switch.

Кнопки соответствуют **буквам Switch**: A — подтверждение, B — отмена/перекат
(`input_xbox_layout = false`). Остальные настройки — в `ds2.toml`.

### Максимальный FPS

Для наибольшего FPS в портативном режиме запускайте готовую PGO+LTO-сборку
с плитки **DS2 в HOME** и выберите рекомендуемый профиль максимального FPS:
**FSR 1 + фиксированные 540p + отключённый лимит 30 fps**.

| Комбинация | Действие |
|---|---|
| L + R + Минус | Включить/выключить ограничение 30 fps |
| L + R + Плюс | Включить/выключить динамическое разрешение |
| L + R + нажатие правого стика | Динамическое / фиксированные 720p / фиксированные 540p |
| L + R + нажатие левого стика | Переключить апскейлер — выберите FSR 1 |

Сделайте копию `ds2.toml`, закройте игру и измените существующие ключи
(отсутствующий ключ высоты добавьте; дубликаты TOML недопустимы):

```toml
present_effect = "fsr"
ds2_frame_cap_30 = false
ds2_dynamic_resolution = false
sa2_render_height_handheld = 540
ds2_vpos_render_scale = true
```

Затем перезапустите игру. Текущий режим виден в уведомлении.
Для более ровных 30 fps верните лимит,
динамическое разрешение и высоту 720 (удалите строку фиксированных 540p).

Основные замеры: **OLED, портатив, CPU 1785 / GPU 921,6 / RAM 2133 МГц**.
Частоты настроены внешними средствами; порт сам не устанавливает разгон
и не выставляет эти три значения. Если у вас уже настроен совместимый менеджер
частот, профиль forwarder относится к Title ID **`01445332534F0000`**.
Проверьте реальные частоты после HOME. Это условия теста конкретной консоли,
а не универсальный максимум для всех моделей Switch.

Исторические замеры без лимита: статичная Маджула около **33 fps при 720p**
и **40 fps при 540p**, CPU-зависимая Башня Хейда около **32 fps**.
Это прежние оптимизированные сборки, не новый замер `1.10.0-access1`.
540p снижает нагрузку на GPU ценой чёткости, но не устраняет CPU/подгрузки;
стабильные 60 fps и прирост от четвёртого ядра не подтверждены.
FSR/FXAA оставьте как в готовом конфиге: выигрыш от отключения не измерен.
PGO ZIP для игры не нужен — оптимизации уже входят в NRO.

### Онлайн

Готовый конфиг использует **`ds2scholar.download`** с включённым серверным реле;
проброс портов на роутере не нужен. Доступность зависит от сервера проекта.
Проверены записки, оценки, пятна крови, призраки, знаки призыва и имена игроков.
Призывы и вторжения Switch/PC прошли проверки 29 октября 2026 года;
после исправления повторных подключений **1 ноября** снова подтверждён вход
в мир в обе стороны.

Онлайн-личность зависит от пользователя Switch. Кириллица в нике переводится
в латиницу; для неподходящих имён используется `Player-XXXX`. Свой ник задайте
в `ds2.toml`: `net_profile_name = "YourName"`. Допустимы латинские буквы,
цифры, пробел и `_ - .`, до 15 символов. При переходе на личность пользователя
старые сохранения копируются один раз; исходная папка остаётся.

Сквозная проверка серверного доступа по ключу консоли (`access1`) ещё не завершена;
метка версии NRO сама по себе не подтверждает работу этого режима.

### Ограничения и помощь

- Цель — 30 fps с динамическим разрешением 720p/540p, FSR 1 и FXAA. Основные
  замеры: Switch OLED, портативный режим, CPU 1785 / GPU 921,6 / RAM 2133 МГц.
  При загрузках и в тяжёлых сценах бывают просадки; результат на штатных частотах
  не обещается. ТВ режим проверен менее полно.
- Полное прохождение, все DLC-локации, кооператив с 3–4 игроками и восстановление
  сети после сна полностью не проверены.
- Падение PC с чтением нулевого адреса после возврата из призыва ещё не устранено;
  такое же падение на Switch не подтверждено.
- При предупреждении о повторных разрывах мультиплеера используйте Bone of Order
  («Кость порядка») у затронутого персонажа. Настройки сервера эту блокировку не снимают.
- В углу кузницы Макдаффа наблюдались мерцание освещения/чёрный квадрат.

Логи: `sdmc:/switch/ds2scholar-nx/logs/ds2_NNN.log` (наибольший номер — последний).
В сообщении об ошибке приложите последний лог, версию, локацию, действия перед
сбоем и портативный/ТВ режим.

Отдельный **PGO ZIP нужен только для повторной сборки**, для игры он не требуется:
[инструкция PGO](../pgo-profile.md), [повторная сборка](../rebuild.md).
При распаковке из клона исходников используйте `tools/` вместо `extract-tools/`.
