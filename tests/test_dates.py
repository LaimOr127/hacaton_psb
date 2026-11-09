from datetime import date

import dates

OLD = "РЕДАКЦИЯ УТРАТИЛА СИЛУ с 01.03.2025.\nРЕГЛАМЕНТ\nРедакция от 10.01.2023\n2.4. Свыше 10 000 000 рублей.\n"
NEW = "РЕГЛАМЕНТ\nРедакция от 01.03.2025. Действует с 01.03.2025.\n2.4. Свыше 15 000 000 рублей.\n"


def test_event_period_precision():
    assert dates.event_period("заключали в августе 2024 года") == (date(2024, 8, 1), date(2024, 8, 31))
    assert dates.event_period("подписан 05.03.2025") == (date(2025, 3, 5), date(2025, 3, 5))
    assert dates.event_period("с 1 марта 2025 г.") == (date(2025, 3, 1), date(2025, 3, 1))
    assert dates.event_period("ставка в 2024 году") == (date(2024, 1, 1), date(2024, 12, 31))
    assert dates.event_period("максимально 2024 года") is None
    assert dates.event_period("без даты") is None


def test_edition_applicability_by_event_date():
    august_2024 = dates.event_period("в августе 2024 года")
    assert dates.edition_note(OLD, august_2024).endswith("К дате события применима.")
    assert dates.edition_note(NEW, august_2024).endswith("К дате события не применима.")
    april_2025 = dates.event_period("в апреле 2025 года")
    assert dates.edition_note(OLD, april_2025).endswith("не применима.")
    assert dates.edition_note(NEW, april_2025).endswith("К дате события применима.")


def test_edition_note_without_event_states_period_only():
    assert dates.edition_note(OLD, None) == "Срок действия редакции: с 10.01.2023 до 01.03.2025 (утратила силу)."
    assert dates.edition_note("ДОГОВОР № 1\n1.1. Текст.\n", None) == ""


def test_law_change_after_event_is_flagged():
    point = "Пункт 3 изменен с 1 января 2026 г. - Федеральный закон\n3. Ставка 22 процента."
    assert "изменена с 01.01.2026" in dates.law_change_note(point, dates.event_period("в 2024 году"))
    assert dates.law_change_note(point, dates.event_period("в 2026 году")) == ""
    assert dates.law_change_note(point, None) == ""
