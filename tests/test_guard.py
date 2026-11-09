import guard

SOURCES = """[1] ТК РФ, ст. 70. Испытание при приеме на работу
Срок испытания не может превышать трех месяцев. Федеральный закон № 152-ФЗ.
[2] Договор поставки № П-17/2024
4.2. Покупатель оплачивает Товар в течение 30 (тридцати) календарных дней.
7.1. Неустойка 0,1% от стоимости. Цена 8 400 000 рублей. Действует с 01.03.2025.
<вопрос>Почему плата 500 000 рублей?</вопрос>"""


def test_supported_answer_passes():
    answer = (
        "Оплата в течение 30 календарных дней (п. 4.2), неустойка 0.1% (п. 7.1), цена 8 400 000 руб. "
        "Источник: ТК РФ, ст. 70; 152-ФЗ. Редакция с 1.03.2025. Плата не 500 000 рублей."
    )
    assert guard.check(answer, SOURCES) == []


def test_invented_facts_are_reported():
    answer = "Срок оплаты 90 дней (п. 4.7). См. ГК РФ, ст. 506, ст. 70 НК РФ и 99-ФЗ."
    assert guard.check(answer, SOURCES) == ["4.7", "506", "90", "99", "99-ФЗ", "ГК РФ, ст. 506", "НК РФ, ст. 70"]


def test_single_digit_reference_is_checked_but_plain_digit_is_not():
    assert guard.check("Срок 3 рабочих дня, ДС № 1.", SOURCES) == []
    assert guard.check("См. п. 9.", SOURCES) == ["9"]


def test_strip_keeps_only_supported_sentences():
    answer = "Оплата в течение 30 дней (п. 4.2). Пени 5% в день. Остальное по договору."
    assert guard.strip(answer, ["5"]) == answer  # "5%" is "5", single digit outside a reference
    assert guard.strip("Оплата 30 дней (п. 4.2). Пени 15% в день.", ["15"]) == "Оплата 30 дней (п. 4.2)."


def test_article_number_followed_by_law_number_is_not_one_number():
    assert guard.check("По ст. 9 152-ФЗ нужно согласие.", "Статья 9. Федеральный закон N 152-ФЗ") == []
