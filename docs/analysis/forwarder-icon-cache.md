# Иконка NSP и установленная плитка — 2026-11-05

Владелец переустановил вариант с картинкой, но HOME продолжал показывать
прежнюю стандартную иконку homebrew. Повторной сборки наугад не выполнялось.

## Проверка самого NSP

Локально прочитаны PFS0 и зашифрованные NCA собственного NSP:
AES-XTS заголовка и AES-CTR секции Control, затем RomFS. Использован
установленный libcrypto через ctypes, без установки Python-пакетов.
Ключи остаются в памяти процесса и не выводятся.

Пакет SHA256:
`9557fc5968a0d3c5c90a7b6952c046a5c587281bdbd58161607f265eefe7617e`.
Control NCA: `5bf43dc2ec948bbc3db4cf204d38adcb`.
Внутри: control.nacp16384Б и icon_AmericanEnglish.dat14722Б.
Иконка SHA256:
`3844d081d1d92d670d9d1f3d86a85c1d7b059c19823b94cd230c595f199c1ca3`.
Это точно подготовленный JPEG DS2, не стандартная иконка libnx.
CNMT package version0. NACP language flags0xBFF; картинки других языков
не упакованы. Это отмечено при исследовании, но языковая политика не менялась.

## Проверка установленного приложения

Добавлена read-only NRO `DS2 HOME icon probe`:
`tools/switch/forwarder_icon_probe.c`, сборка
`tools/win/build_forwarder_probe.ps1` через run.ps1.
Она читает NS CacheOnly/StorageOnly и NCM LatestContentMetaKey/Control ID
только для TitleID01445332534F0000. Контент, метаданные, кеш и сохранения
не изменяются; пишутся лишь собственные отчёты в
`/switch/ds2scholar-nx/forwarder_probe/`.

Реальная сборка exit0, NRO243909Б; загружена через switch_upload --backup.
Владелец выполнил запуск, отчёт и картинки скачаны по FTP.

- NS initialization0; CacheOnly result0x6410, данных нет.
- StorageOnly result0,31106Б: NACP16384+JPEG14722.
- SHA256 JPEG из установленного приложения точно совпадает с картинкой DS2.
- SHA256 NACP: `9c1cf4c94b49201e71e2bb39c3a11f2e5bc4e9ffb4cff2f1c132ddc896bbebe3`.
- NCM SD storage5: version0,type0x80,Control ID
  `5bf43dc2ec948bbc3db4cf204d38adcb` — соответствует новому NSP.
- В BuiltInUser этого Title ID нет (latest0xE05).

Следовательно, новый пакет установлен, картинка не теряется при упаковке
или установке. Причина расхождения с HOME пока не доказана; ведущая гипотеза —
кеш отображения HOME при замене приложения с тем же ID и version0.
CacheOnly NS и внутренний кеш HOME не следует считать одной сущностью.

После полного перезапуска консоли/Atmosphère владелец подтвердил:
«Да, появилась». Изображение HOME обновилось без изменения NSP или установки
ещё одного пакета. Для этого случая причиной было сохранение старого
отображения HOME; повторная упаковка и смена Title ID/версии не потребовались.
Удаление приложения, явный сброс кеша и изменение CNMT не выполнялись.

Логи основной папки:logs/forwarder_packed_icon_inspect.log,
logs/forwarder_probe_upload.log,logs/forwarder_probe_results.log.
Лог сборки probe — logs/forwarder_probe_build.log экспериментального worktree.
Локальные отчёты:out/packed_forwarder_forwarder-access1-icon.json и
out/forwarder-probe-results/. Производственный NSP/NRO/TOML не заменялись.
