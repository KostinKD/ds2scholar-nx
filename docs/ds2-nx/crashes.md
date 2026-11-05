# Журнал крэшей

Каждый разобранный крэш — одна запись. Перед разбором нового сначала поискать здесь по симптому.

Классы (porting-guide.md, разделы 3.2 и 4.3):

| Класс | Симптом | Инструмент |
|---|---|---|
| Функция по указателю (vtable, CRT, callback) | unregistered call | tools/pointer_fixpoint.py, pointer_audit.py |
| Обрезанная jump-таблица | illegal instruction, switch case out of range | tools/switch_check.py |
| Дыра между функциями | крэш в коде, которого нет в C++ | tools/find_gaps.py, gap_fixpoint.py |
| setjmp / longjmp | r1 / r31 испорчены после возврата | поиск по форме, setjmp_address / longjmp_address |
| noreturn (abort, throw) | ложный fall-through, catch-funclet слит с родителем | tools/read_before_write.py --noreturn= |
| Ядро / XAM | зависание или ошибка на системном вызове | лог импортов, заглушка в SDK |
| Только на Switch | см. sa2-nx porting-guide 7.4 и nfsmw-nx platform-notes.md | — |

## Записи

<!--
### YYYY-MM-DD — короткое имя
- Этап / где: (меню, Маджула, загрузка сейва...)
- Симптом: (строка лога, адрес)
- Гостевая функция: sub_8XXXXXXX (как найдена: llvm-symbolizer ds2.exe+0xRVA)
- Класс:
- Исправление: (запись манифеста / хук / правка SDK) + доказательство
- Проверено: (какой запуск) / НЕ проверено:
-->
