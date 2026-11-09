import kb
from search import Index


def _doc(name: str, text: str) -> kb.Document:
    return kb.parse_document(name, text)


DOCS = [
    _doc(
        "документы__Договор поставки П-17-2024 Альфа-Трейд.txt",
        "ДОГОВОР ПОСТАВКИ № П-17/2024\nООО «Альфа-Трейд»\n5. Гарантия\n5.1. Гарантийный срок 24 месяца.\n",
    ),
    _doc(
        "документы__Договор поставки ПТ-05-2023 Альфа-Трейдинг.txt",
        "ДОГОВОР ПОСТАВКИ № ПТ-05/2023\nООО «Альфа-Трейдинг»\n6. Гарантия\n"
        "6.1. Гарантию устанавливает производитель.\n",
    ),
    _doc(
        "документы__Договор аренды А-08-2024.txt",
        "ДОГОВОР АРЕНДЫ № А-08/2024\n3. Арендная плата\n3.1. Арендная плата 450 000 рублей.\n",
    ),
]


def test_contract_number_finds_its_contract():
    index = Index(DOCS)
    assert index.context("гарантия по договору ПТ-05/2023")[0].doc.title.startswith("Договор поставки ПТ-05")


def test_similar_counterparties_are_not_merged():
    index = Index(DOCS)
    top = index.context("гарантия у Альфа-Трейдинг")[0]
    assert "Альфа-Трейдинг" in top.doc.title


def test_small_document_is_given_whole_once():
    index = Index(DOCS)
    blocks = index.context("арендная плата аренда А-08/2024")
    rent = [b for b in blocks if "аренды" in b.doc.title]
    assert len(rent) == 1
    assert rent[0].text == rent[0].doc.text
    assert rent[0].address == ""
