import kb
import relations

CONTRACT = "ДОГОВОР ПОСТАВКИ № П-17/2024\nг. Москва — 12 февраля 2024 г.\n3. Поставка\n3.2. Адрес доставки: Москва.\n"
AGREEMENT = (
    "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1\nк договору поставки № П-17/2024 от 12 февраля 2024 г.\n"
    "Изложить пункт 3.2 договора в следующей редакции: Химки.\n"
)
OTHER_CONTRACT = "ДОГОВОР ПОСТАВКИ № ПТ-05/2023\n4. Расчёты\n4.1. Оплата в течение 45 дней.\n"
OLD_EDITION = (
    "РЕДАКЦИЯ УТРАТИЛА СИЛУ с 01.03.2025.\nРЕГЛАМЕНТ СОГЛАСОВАНИЯ ДОГОВОРОВ ООО «МЕРИДИАН»\n"
    "Редакция от 10.01.2023\n2. Порядок\n2.4. Свыше 10 000 000 рублей.\n"
)
NEW_EDITION = (
    "РЕГЛАМЕНТ СОГЛАСОВАНИЯ ДОГОВОРОВ ООО «МЕРИДИАН»\nРедакция от 01.03.2025. Действует с 01.03.2025.\n"
    "2. Порядок\n2.4. Свыше 15 000 000 рублей.\n"
)
LETTER = "ООО «МЕРИДИАН»\nСлужба комплаенс\nИсх. № К-12 от 15.04.2025\nО проверке контрагентов.\n"
MEMO = "ООО «МЕРИДИАН»\nЮридический отдел\nСЛУЖЕБНАЯ ЗАПИСКА № ЮО-7\nО хранении договоров.\n"


def _docs(**texts):
    return {key: kb.parse_document(f"документы__{key}.txt", text) for key, text in texts.items()}


def test_agreement_is_linked_to_its_contract_both_ways():
    docs = _docs(contract=CONTRACT, agreement=AGREEMENT, other=OTHER_CONTRACT)
    links = relations.link(list(docs.values()))
    assert links[docs["contract"].doc_id] == [docs["agreement"].doc_id]
    assert links[docs["agreement"].doc_id] == [docs["contract"].doc_id]
    assert docs["other"].doc_id not in links


def test_editions_of_one_document_are_linked():
    docs = _docs(old=OLD_EDITION, new=NEW_EDITION)
    links = relations.link(list(docs.values()))
    assert links[docs["old"].doc_id] == [docs["new"].doc_id]
    assert links[docs["new"].doc_id] == [docs["old"].doc_id]


def test_documents_with_same_letterhead_are_not_editions():
    docs = _docs(letter=LETTER, memo=MEMO)
    assert relations.link(list(docs.values())) == {}
