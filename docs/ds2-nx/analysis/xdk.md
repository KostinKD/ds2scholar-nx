# XDK, компилятор и middleware (этап 1)

Воспроизвести: `python tools/xex_headers.py assets/game_root/Default.xex` (→ `logs/xex_headers.log`).
Строки middleware взяты из расшифрованного PE (см. [xex.md](xex.md), раздел о расшифровке); адреса — VA строки
в образе.

## XDK

**XDK 2.0.21256.0** — все библиотеки XDK в opt. header `0x000200FF` (static libraries) одной версии:

| Библиотека | Версия | approval |
|---|---|---|
| XNET | 2.0.21256.0 | 2 |
| XONLINE | 2.0.21256.0 | 2 |
| XAPILIB | 2.0.21256.0 | 2 |
| D3D9 | 2.0.21256.0 | 2 |
| D3DX9 | 2.0.21256.0 | 2 |
| XGRAPHC | 2.0.21256.0 | 2 |
| XBOXKRNL | 2.0.21256.0 | 2 |
| XAUDIO2 | 2.0.21256.0 | 2 |
| XAPOBA | 2.0.21256.0 | 2 |
| XMP | 2.0.21256.0 | 2 |
| XMIC | 2.0.21256.0 | 2 |
| XMCORE | 2.0.21256.0 | 2 |
| XHV2 | 2.0.21256.0 | 2 |
| XPARTY | 2.0.21256.0 | 2 |
| XWMAD | 2.0.21256.0 | 2 |
| LIBCPMT | 2.0.11886.0 | 0 |
| LINK | 10.0.11886.0 | 2 |
| C2 | 16.0.11886.0 | 2 |
| C1 | 16.0.11886.0 | 2 |

Подтверждение: импорты `xam.xex` и `xboxkrnl.exe` тоже версии 2.0.21256.0 (минимум 2.0.16537.0).

- Компилятор: C1/C2 16.0.11886 (ветка MSVC 2010 под Xbox 360), LINK 10.0.11886; CRT — LIBCPMT (Dinkumware,
  строка 0x8345E018).
- Не проверено: какому месяцу/названию релиза XDK соответствует сборка 21256.

### Что это значит для порта

- **D3D9 + D3DX9 + XGRAPHC** — рендер через стандартный D3D9 Xenos; шейдеры прекомпилированы (`.fxo`, см.
  [files.md](files.md)).
- **XAUDIO2 + XAPOBA** — выход звука; звук игры идёт через FMOD (ниже), который сидит поверх XAudio2.
- **XMCORE + XWMAD** — XMedia: проигрывание WMV/WMA. Нужно для `movie/prologue.wmv`. В PE есть секция
  `.XBMOVIE` и строка устройства `\??\xbmovie:` (0x8343C968).
- **XMIC, XHV2, XPARTY, XONLINE, XNET** — микрофон, голосовой чат, party, Live — для оффлайн-порта вероятные
  заглушки.
- **XMP** — фоновая музыка пользователя (Xbox Music Player).

## Middleware (из строк PE)

| Компонент | Версия | Доказательство |
|---|---|---|
| FMOD Ex (+ FMOD Event) | 4.40.05 | `N:\FMOD_FRPG2\Source\fmodexsrc44005\fmod4\...` (0x82047EA7 и др.); строки `FMOD FSB 5 Codec` (0x8204B5A4) |
| Havok | 2012.1.0-r1 | `hk_2012.1.0-r1` (0x820E7F6C); путь `...\Havok_2012_1_0\hk2012_1_0_r1\...` (0x82164B78) |
| NaturalMotion morpheme | 4 (по путям) | `chr:/morpheme4/chr/c%04d.%s` (0x82009E7D); папка `morpheme4\` в архивах. Точная версия не найдена |
| zlib | 1.2.7 | `deflate 1.2.7 Copyright 1995-2012` (0x821B87E8), `inflate 1.2.7` (0x821BBE30) — распаковка DCX/DFLT |
| IJG libjpeg | (не определена) | `Copyright (C) 1998, Thomas G. Lane` (0x8208391C) |
| Geomerics Enlighten | (не определена) | `title:/Test/Enlighten/...` (0x82018C51 и др.) — отладочные пути, используется ли в релизе — не проверено |
| DirectXMath / XNAMath | — | `XMVector*` строки (0x8208C930…) — похоже на генератор кода шейдеров/выражений, не разбиралось |

Не проверено: Scaleform/Bink/Wwise/CRI — поиск по строкам их не нашёл (`grep -i` по `scaleform|bink|wwise|cri `);
это отсутствие строк, а не доказательство отсутствия кода.
