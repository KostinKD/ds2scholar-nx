# XDK, компилятор, middleware SotFS (этап 1)

Воспроизвести: `python -I tools/xex_headers.py assets/game_root/Default.xex` (→ `logs/xex_headers.log`).
Строки — из расшифрованного PE (см. [xex.md](xex.md)), адреса — VA строки.

## XDK — тот же, что у DS2

**XDK 2.0.21256.0** — opt. header `0x000200FF` перечисляет те же 19 библиотек, что у DS2 TU0, с теми же версиями
и approval ([docs/ds2-nx/analysis/xdk.md](../ds2-nx/analysis/xdk.md)): XNET, XONLINE, XAPILIB, **D3D9, D3DX9,
XGRAPHC**, XBOXKRNL, XAUDIO2, XAPOBA, XMP, XMIC, XMCORE, XHV2, XPARTY, XWMAD — все 2.0.21256.0 (approval 2);
LIBCPMT 2.0.11886.0 (approval 0); LINK 10.0.11886.0; C1/C2 16.0.11886.0. Импорты xam/xboxkrnl — тоже
2.0.21256.0 (min 2.0.16537.0).

Вывод: тот же компилятор (MSVC 2010 под Xbox 360, сборка 11886) и та же библиотека D3D9 → код D3D и CRT
совпадает с DS2 с точностью до адресов (подтверждено ниже по байтам).

## D3D

Библиотека D3D9 той же версии, и это подтверждено кодом: все D3D-функции, найденные в DS2
([docs/ds2-nx/analysis/d3d.md](../ds2-nx/analysis/d3d.md)), нашлись в SotFS по маскированной сигнатуре с
**единственным** кандидатом (`logs/sigmatch_d3d.log`; метод — [xex.md](xex.md#сопоставление-функций-с-ds2-по-маскированной-сигнатуре)):

| Функция | DS2 | SotFS (кандидат) |
|---|---|---|
| обработчик прерываний GPU | 0x829A7F70 | 0x829D8140 |
| flip | 0x829BA620 | 0x829EA7E8 |
| настройка дисплея | 0x829BA750 | 0x829EA918 |
| `D3DDevice_Swap` | 0x829BB520 | 0x829EB6E8 |
| загрузка шейдеров (FlushState) | 0x829BF328 | 0x829EF4F0 |
| сброс шейдерных констант | 0x829BE590 | 0x829EE758 |
| сброс fetch-констант | 0x829BE438 | 0x829EE600 |
| группы регистров | 0x829BE1F8 | 0x829EE3C0 |
| `BeginVertices` / `DrawVerticesUP` | 0x829C2340 / 0x829C2800 | 0x829F2508 / 0x829F29C8 |
| `BeginIndexedVertices` / `DrawIndexedVerticesUP` | 0x829C2848 / 0x829C2D88 | 0x829F2A10 / 0x829F2F50 |
| `DrawVertices` / `DrawIndexedVertices` | 0x829C2E28 / 0x829C3240 | 0x829F2FF0 / 0x829F3408 |
| кандидат в Clear (`DRAW_INDX_2`) | 0x829CBAE8 | 0x829FBCB0 |
| прочие из d3d.md (`829AC6C0`, `829AC818`, `829B0E48`, `829BDE68`, `829BE2B8`, `829C3E88`, `829CB130`) | | 0x829DC890, 0x829DC9E8, 0x829E1010, 0x829EE030, 0x829EE480, 0x829F4050, 0x829FB2F8 |
| обёртка движка над DrawIndexedVertices | 0x82EFC250 | 0x82F30728 |
| обёртка движка над DrawVertices | 0x82EFC1D0 | 0x82F306A8 **или** 0x82F306E8 (два кандидата) |

Сдвиг в этой зоне +0x301C8…+0x301D0. Маска обнуляет смещения D-form load/store, поэтому смещения device
(VS +0x3310 / PS +0x330C у DS2) этим методом **не проверены** — проверить листингом 0x829EF4F0 на этапе 4.
**Не проверено:** вызовы в рантайме (`ds2_d3d_census_s`), вызывающие (`tools/d3d_find.py callers`) — нужен
кодоген SotFS (этап 2).

Для порта: хуки `app/src/ds2_me_hooks.cpp`, `app/src/me/*` переносятся заменой адресов по этой таблице после
подтверждения; рендерер (EDRAM, резолвы) от адресов не зависит.

## Middleware (из строк PE) — то же, что у DS2

| Компонент | Версия | SotFS | DS2 |
|---|---|---|---|
| FMOD Ex (+ Event) | 4.40.05 | `fmodexsrc44005` 0x8204923D; `FMOD FSB 5 Codec` 0x8204E80C | 0x82045FD5 / 0x8204B5A4 |
| Havok | 2012.1.0-r1 | `hk_2012.1.0-r1` 0x820EB36C; `Havok_2012_1_0` 0x821688C7 | 0x820E7F6C / 0x82164BA7 |
| zlib | 1.2.7 | `deflate 1.2.7` 0x821BC429, `inflate 1.2.7` 0x821BFA71 | 0x821B87E9 / 0x821BBE31 |
| IJG libjpeg | — | `Thomas G. Lane` 0x82086C20 | 0x82083930 |
| morpheme | 4 (по путям) | `dlc_data:/morpheme4/chr/…` и др. | то же |
| Enlighten | — | `title:/Test/Enlighten/…` 0x8201B1F8 | есть |
| XMedia (WMV) | — | секция `.XBMOVIE`, `xbmovie:` 0x8346CEEC | 0x8343C96C |

Scaleform/Bink/Wwise/CRI в строках не найдены (как и у DS2; отсутствие строк ≠ отсутствие кода).
