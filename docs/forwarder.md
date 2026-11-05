# DS2 SotFS — запуск с HOME

Собственный NSP-forwarder запускает существующий
`sdmc:/switch/ds2scholar-nx/ds2.nro`. Title ID: `01445332534F0000`.
Это отдельный эксперимент; ядра0–3 разрешены процессу, но маски потоков
игры и конфиг не меняются. Прирост FPS не измерен.

## Установка и проверка

1. Установить `ds2scholar-forwarder.nsp` через DBI из папки
   `SD:/switch/ds2scholar-nx/` и запустить новую плитку с HOME.
2. Выбрать прежнего пользователя Switch: сохранения и онлайн-личность
   зависят от пользователя. У forwarder выставлен StartupUserAccount=Required.
3. Проверить загрузку игры, сохранения, HOME/возврат и выход. Затем сон и онлайн.
4. В новом `logs/rex/rex_profile.log` проверить `process cores 4 (mask 0xf)`.
   Это подтверждает разрешение процесса, но не загрузку всех ядер потоками.

При обновлении обложки установить новый NSP поверх прежнего через DBI.
Простое копирование NSP на SD не изменяет картинку уже установленной плитки.
Title ID сохраняется прежним.
Если после переустановки осталась старая иконка, полностью перезапустить
консоль/Atmosphère: в проверке05.11 это обновило изображение HOME.

Папка игры и NRO остаются на SD. Замена системного `atmosphere/hbl.nsp`
для этого способа не требуется. Имя, версия и иконка взяты из NRO;
в текущем NRO используется стандартная иконка libnx. Для своей обложки
forwarder передать `-Icon путь/к/icon.jpg`: baseline RGB JPEG256×256.
Без `-Icon` сохраняется прежнее использование картинки NRO.

## Сборка на Windows

Установить devkitA64/libnx, devkitPro tools, MSYS2 с make и MinGW GCC,
Python3.12+ и Git. Используется локальный `prod.keys`; его содержимое
не выводится и не включается в результаты. В этой среде есть junction
`G:/devkitPro` без пробелов к установленному SDK: короткий путь важен для make.

```powershell
$env:SA2_LLVM = 'G:\Program Files\LLVM'
$env:SA2_VSDIR = 'G:\Program Files\VisualStudio'
$env:DEVKITPRO = 'G:/devkitPro'
$env:MSYS2_ROOT = 'G:/msys64'
$env:SWITCH_PROD_KEYS = 'путь/к/своему/prod.keys'
tools/win/run.ps1 logs/forwarder_build.log "powershell -NoProfile -ExecutionPolicy Bypass -File tools/win/build_forwarder.ps1"
```

По умолчанию вход — `out/nx_pgo/ds2.nro`, выход — пустая папка
`out/forwarder/`. Аргументы wrapper: `-Nro`, `-Keys`, `-Deps`, `-Output`,
`-MaxCpu 3`, `-Icon`. `-MaxCpu 2` разрешает ядра0–2 для отдельного A/B.
Выходная папка должна быть пустой; старые релизные файлы не заменяются.

Зависимости автоматически скачиваются в `out/forwarder-deps/`, либо
передаются через `-Deps`. Проверяются revisions и tracked-изменения;
в сборку экспортируется только Git-дерево указанного коммита, без untracked
исходников и оставшихся объектов:

- Forwarder-Mod: `9853bd9167d5a7f0c5fdf935864245c1fbcf8282`.
- hacBrewPack: `745b16ecfc9ce055743067d200572204cb2aac6c`.

Локальная совместимость загрузчика с новым libnx: единственное старое
объявление `void NORETURN` заменяется на атрибут noreturn при подготовке
копии исходников. NRO игры не пересобирается.

Проверка готовой папки, без ключей и компиляции:

```powershell
tools/win/run.ps1 logs/forwarder_verify.log "python -I tools/forwarder.py --verify-output out/forwarder"
tools/win/run.ps1 logs/forwarder_tests.log "python -I -m unittest discover -s tools/tests -p test_forwarder.py"
```

Проверяются границы ASET NRO, JPEG/NACP, целевой путь, ядра и приоритеты
в обеих таблицах NPDM, 39-bit и Title ID. После работы packer NPDM проверяется
повторно. NSP содержит ровно3 NCA; проверяются структура PFS0 и хеши файлов
папки релиза. Содержимое зашифрованных NCA независимо не расшифровывается:
проверка разрешений опирается на NPDM сборки и закреплённый packer.
Окончательная проверка — запуск на консоли и фактическая маска процесса.

## Результат 2026-11-05

Итоговая native-сборка: exit0, NSP277208Б,15/15 unittest.
Независимое ревью: замечание к untracked-входам исправлено с RED→GREEN;
проверка нестандартного Title ID в verifier также исправлена с RED→GREEN.
NPDM ACI0/ACID:0–3, приоритеты28–59,39-bit. NACP:Required.

Артефакт в основной рабочей папке:
`out/release/forwarder-access1-final/ds2scholar-forwarder-1.10.0-access1-core3.nsp`.
SHA256: `39e16a656afe576b5df04c97dbe29b62611688efc25118e26fd8d058fb344d13`.
NRO-цель:1.10.0-access1, SHA256
`3925ee73ec8b73da36c875f64b081405a38e3bddee3750570b9ce92655249d67`.

NSP загружен через `switch_upload.py --backup` в
`/switch/ds2scholar-nx/ds2scholar-forwarder.nsp`; повторное скачивание
подтвердило277208Б и SHA256. Игровые файлы, NRO, TOML и сохранения
на консоли не заменялись.

Логи сборки и15 тестов — в `out/worktrees/forwarder/logs/` основной рабочей
папки: `forwarder_build_reviewed_20261105.log`, `forwarder_review_green.log`,
`forwarder_final_verify_20261105.log`. Логи FTP — в основном `logs/`:
`forwarder_upload_20261105.log`, `forwarder_ftp_verify_20261105.log`.
В папке артефактов находятся лицензии, SHA256SUMS и validation.json.

Не проверено: установка NSP, запуск с HOME, выбор пользователя/сохранения,
реальная маска0xf, сон/возврат/выход, онлайн и производительность.
Ветка `experiment/home-forwarder-20261105` остаётся отдельной до проверки.

## Подтверждение HOME и обложка

Владелец05.11 подтвердил: «Игра запустилась, все окей», сообщил об отсутствии
обложки. FTP:192 лога проверено,3 изменённых скачано. Сеанс ds2_189:
15:02:29–15:03:05, профиль4ядра/0xF, пользователь `preselected user`.
Fatal/critical0,shader-library misses0,15117 проверок замен/0 различий.
Это подтверждает доступ к core3 и передачу пользователя, но не прирост FPS.

В ветке `experiment/home-forwarder-icon-20261105` добавлен необязательный
аргумент `--icon`/`-Icon`;2 новых теста RED→GREEN, всего17/17.
Проверяются JPEG-заголовок baseline/8-bit/RGB256×256 и применение override
без изменения NACP/пользователя/Title ID. Проверка заголовка не заменяет
полный декодер; фактический JPEG декодирован и просмотрен отдельно.

Картинка извлечена из thumbnail заголовка собственной GoD-копии:64×64 PNG,
11784Б (стандартные STFS/SVOD поля size0x1712,data0x171A; структура описана
в sdk/include/rex/filesystem/devices/stfs_xbox.h). Подготовлена JPEG256×256,
14722Б средствами System.Drawing. Это форматирование исходной картинки,
не генерация нового рисунка. Картинки игры остаются в ignored out/,в Git не входят.
JPEG SHA256: `3844d081d1d92d670d9d1f3d86a85c1d7b059c19823b94cd230c595f199c1ca3`.

Новый пакет: `out/release/forwarder-access1-icon/`,NSP277208Б,
SHA256 `9557fc5968a0d3c5c90a7b6952c046a5c587281bdbd58161607f265eefe7617e`.
Title ID01445332534F0000,39-bit,обе таблицы0–3,выбор пользователя Required.
Сборка и verify-output:exit0. NSP загружен с --backup в тот же SD-путь.
Предыдущий файл сохранён в out/switch_upload/backup/ds2scholar-forwarder.nsp.
Повторное скачивание подтвердило SHA256 нового NSP;SHA256 бэкапа совпал
с прежним пакетом39e16a65…44d13. Лог:logs/forwarder_icon_ftp_verify.log основной папки.

Логи: forwarder_icon_red.log,forwarder_icon_green.log,forwarder_icon_build_20261105.log,
forwarder_icon_verify.log в logs/экспериментального worktree;FTP-сбор и передача —
logs/forwarder_boot_collect_20261105.log и logs/forwarder_icon_upload.log основной папки.
Не проверено:переустановка NSP с обложкой и её отображение HOME;сон/онлайн/FPS.

Обновление: владелец переустановил NSP, но в HOME осталась стандартная иконка.
Read-only probe подтвердил новый установленный Control NCA и точный SHA256
картинки DS2. После полного перезапуска владелец подтвердил появление обложки;
новый NSP не понадобился. Исследование и результат —
[forwarder-icon-cache.md](analysis/forwarder-icon-cache.md).

## Картинка, выбранная владельцем

Владелец05.11 выбрал [изображение с Dark Souls Wiki](https://static.wikia.nocookie.net/darksouls/images/2/27/Dark_Souls_II_Scholar_of_the_First_Sin_-_A_New_Darkness/revision/latest/scale-to-width-down/250?cb=20160220204116&path-prefix=ru).
Получен исходник480×269;SHA256
`6f605d888da11e2ea8761b883d61d019e82cb2dcf7c5168b553cb7b2e657e636`.
Подготовлен квадратный центральный crop269×269,x105/y0,затем256×256 без
растяжения. Название и подзаголовок сохранены;результат просмотрен.
JPEG baseline RGB,качество95,28095Б,SHA256
`e0b6a092c3f23959f0b6ea830e6cfa6fd310d728e00bd5bad3e15fb9df44ff6f`.
Исходник и готовая картинка — ignored out/forwarder-wiki-icon/,в Git не входят.

Ветка experiment/forwarder-wiki-cover-20261105. Код сборщика не менялся;
использован существующий -Icon. Новый NSP293592Б,папка
`out/release/forwarder-access1-wiki-cover/` основной рабочей папки,SHA256
`e02ca607d5bab33e233cc63ee5d0107cdeca48794245f5e80100a55979ac66f1`.
Title ID01445332534F0000,39-bit,ядра0–3,user Required,NROaccess1 прежние.
Build/verify-output exit0. Независимое чтение зашифрованного Control NCA
подтвердило JPEG28095Б с нужным SHA256,NACP побайтово прежний.
Пакет загружен с --backup на `/switch/ds2scholar-nx/ds2scholar-forwarder.nsp`;
повторное скачивание побайтово совпало с локальным NSP.

Логи worktree:forwarder_wiki_cover_build.log,forwarder_wiki_cover_verify.log.
Логи основной папки:forwarder_wiki_icon_convert.log,forwarder_wiki_cover_packed.log,
forwarder_wiki_cover_upload.log,forwarder_wiki_cover_ftp_verify.log.
Владелец подтвердил переустановку и появление именно новой выбранной картинки
после перезапуска. Подготовка общего пакета релиза — [release-ready.md](release-ready.md).
