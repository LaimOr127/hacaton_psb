import kb
from citations import sources
from search import Block

RENT = kb.parse_document(
    "документы__Договор аренды А-08-2024.txt",
    "ДОГОВОР АРЕНДЫ № А-08/2024\n3. Плата\n3.1. Плата 450 000 рублей.\n3.2. Вносится до 5-го числа.\n",
)
SUPPLY = kb.parse_document(
    "документы__Договор поставки П-17-2024.txt",
    "ДОГОВОР ПОСТАВКИ № П-17/2024\n3. Поставка\n3.1. Поставка партиями.\n",
)
OLD = kb.parse_document(
    "документы__Регламент согласования договоров ред 2023.txt",
    "РЕГЛАМЕНТ СОГЛАСОВАНИЯ ДОГОВОРОВ\nРедакция от 10.01.2023\n2. Порядок\n2.4. Свыше 10 000 000 рублей.\n",
)
NEW = kb.parse_document(
    "документы__Регламент согласования договоров ред 2025.txt",
    "РЕГЛАМЕНТ СОГЛАСОВАНИЯ ДОГОВОРОВ\nРедакция от 01.03.2025. Действует с 01.03.2025.\n"
    "2. Порядок\n2.4. Свыше 15 000 000.\n",
)
LAW = kb.parse_document(
    "законы__ТК_ст70.txt",
    "Источник: Статья 70. ТК РФ Испытание\n\nСтатья 70. Испытание\n\nСрок испытания не более трех месяцев.\n",
)


def _blocks(*docs):
    return [Block(doc, doc.text, "", [doc.chunks[-1].chunk_id]) for doc in docs]


def _cited(answer, *docs):
    return {s.title: [c.split("#")[1] for c in s.chunk_ids] for s in sources(answer, _blocks(*docs)) if s.cited}


def test_clause_is_highlighted_only_in_the_named_contract():
    cited = _cited("По договору № А-08/2024 плата 450 000 рублей (п. 3.1).", RENT, SUPPLY)
    assert list(cited) == ["Договор аренды А-08-2024"]
    rent_clause = next(c.chunk_id for c in RENT.chunks if c.address == "п. 3.1").split("#")[1]
    assert cited["Договор аренды А-08-2024"] == [rent_clause]


def test_named_edition_wins_over_other_editions():
    answer = "По Регламенту согласования договоров в редакции от 10.01.2023 — свыше 10 000 000 (п. 2.4)."
    assert list(_cited(answer, OLD, NEW)) == ["Регламент согласования договоров ред 2023"]


def test_generic_word_does_not_name_a_document():
    assert _cited("Помогаю только по законам, договорам и внутренним регламентам (п. 2.4).", OLD, NEW) == {}


def test_law_named_by_article_without_point_highlights_best_match():
    cited = _cited("Срок испытания не более трех месяцев. Источник: ТК РФ, ст. 70.", LAW, RENT)
    assert list(cited) == ["ТК РФ, ст. 70. Испытание"]


def test_uncited_documents_are_listed_after_cited_ones():
    result = sources("По договору № А-08/2024 (п. 3.2).", _blocks(SUPPLY, RENT))
    assert [s.cited for s in result] == [True, False]
