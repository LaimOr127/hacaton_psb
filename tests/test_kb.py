import kb

CONTRACT = """ДОГОВОР ПОСТАВКИ № П-17/2024
г. Москва — 12 февраля 2024 г.
1. Предмет договора
1.1. Поставщик обязуется передать Товар.
1.2. Цена согласуется в Спецификациях.
2. Цена договора
2.1. Цена включает НДС по ставке 20%.
"""

LAW = """Источник: Статья 70. ТК РФ Испытание при приеме на работу. Трудовой кодекс (ТК РФ)
URL: https://example.test/
Дата выгрузки: 10.10.2026

Статья 70 изменена с 1 сентября 2026 г. - Федеральный закон от 9 апреля 2026 г. № 91-ФЗ

Статья 70. Испытание при приеме на работу

Срок испытания не может превышать трех месяцев.

Пункт 2 изменен с 1 января 2026 г. - Федеральный закон от 1 января 2025 г. № 1-ФЗ

2. Второй пункт закона.

1) первый подпункт;
"""


def test_contract_clauses_get_addresses_and_section_heading():
    doc = kb.parse_document("документы компании__Договор П-17.txt", CONTRACT)
    assert doc.kind == "company"
    assert doc.title == "Договор П-17"
    by_address = {c.address: c.text for c in doc.chunks}
    assert by_address["п. 1.1"].startswith("1. Предмет договора\n1.1.")
    assert by_address["п. 2.1"].startswith("2. Цена договора\n2.1.")
    assert "п. 1.2" in by_address


def test_chunk_offsets_match_document_text():
    for name, text in (("документы__a.txt", CONTRACT), ("законы__b.txt", LAW)):
        doc = kb.parse_document(name, text)
        assert all(doc.text[c.start : c.end] == c.text for c in doc.chunks)


def test_law_title_and_service_note_glued_to_following_point():
    doc = kb.parse_document("законы__ТК_ст70.txt", LAW)
    assert doc.kind == "law"
    assert doc.title == "ТК РФ, ст. 70. Испытание при приеме на работу"
    point = next(c for c in doc.chunks if c.address == "ст. 70, п. 2")
    assert point.text.startswith("Пункт 2 изменен с 1 января 2026 г.")
    assert "1) первый подпункт" in point.text


def test_unnumbered_law_paragraph_is_addressed_by_article_only():
    doc = kb.parse_document("законы__ТК_ст70.txt", LAW)
    part = next(c for c in doc.chunks if "трех месяцев" in c.text)
    assert part.address == "ст. 70"


def test_federal_law_title():
    text = (
        'Источник: Статья 1. Федеральный закон от 19.06.2000 N 82-ФЗ "О минимальном размере оплаты труда"\n\n'
        "Статья 1. Установить МРОТ.\n"
    )
    doc = kb.parse_document("законы__МРОТ.txt", text)
    assert doc.title == "Федеральный закон № 82-ФЗ «О минимальном размере оплаты труда», ст. 1. Установить МРОТ."
