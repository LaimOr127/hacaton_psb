import numpy as np

import kb
from search import Index, rrf


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


def _keyword_embedder(texts):
    """Maps texts to topic axes; stands in for bge-m3 in tests."""
    topics = (("гаранти", "ремонт"), ("аренд", "помещен"), ("оплат", "деньг"))
    rows = [[float(any(word in text.lower() for word in words)) for words in topics] + [0.1] for text in texts]
    vectors = np.asarray(rows, dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _failing(*args):
    raise RuntimeError("proxy down")


def test_rrf_rewards_agreement_between_rankings():
    fused = dict(rrf([[1, 2, 3], [3, 1, 4]]))
    assert max(fused, key=fused.get) == 1
    assert fused[3] > fused[2]


def test_dense_channel_finds_paraphrase_without_shared_words():
    index = Index(DOCS, embed=_keyword_embedder)
    assert index.vectors is not None
    top = index.context("кто чинит сломанный товар бесплатно, ремонт")[0]
    assert "Гарантия" in top.text


def test_embedding_failure_falls_back_to_lexical_search():
    index = Index(DOCS, embed=_failing)
    assert index.vectors is None
    assert index.context("гарантия по договору ПТ-05/2023")[0].doc.title.startswith("Договор поставки ПТ-05")


def test_reranker_order_is_applied():
    def prefer_rent(query, documents, top_n):
        order = sorted(range(len(documents)), key=lambda i: "аренд" not in documents[i].lower())
        return [(i, 1.0 - n / 10) for n, i in enumerate(order)][:top_n]

    index = Index(DOCS, rerank=prefer_rent)
    assert "аренды" in index.search("гарантия П-17/2024")[0][0].text.lower()


def test_reranker_failure_keeps_fused_order():
    plain = Index(DOCS).search("гарантия П-17/2024")
    broken = Index(DOCS, rerank=_failing).search("гарантия П-17/2024")
    assert [c.chunk_id for c, _ in broken] == [c.chunk_id for c, _ in plain]


def test_related_document_is_placed_next_to_its_contract():
    contract = kb.parse_document(
        "документы__Договор П-17.txt", "ДОГОВОР ПОСТАВКИ № П-17/2024\n3. Поставка\n3.2. Адрес доставки: Москва.\n"
    )
    agreement = kb.parse_document(
        "документы__ДС.txt", "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1\nк договору поставки № П-17/2024\nНовая редакция.\n"
    )
    memo = kb.parse_document("документы__Памятка.txt", "ПАМЯТКА\nОфис в Москве, адрес на сайте.\n")
    blocks = Index([contract, agreement, memo]).context("адрес доставки Москва")
    order = [b.doc.doc_id for b in blocks]
    assert order.index(agreement.doc_id) == order.index(contract.doc_id) + 1


def test_failed_api_channels_are_not_retried_on_every_question():
    calls = {"embed": 0, "rerank": 0}

    def embed_index_only(texts):
        calls["embed"] += 1
        if calls["embed"] > 1:  # index build succeeds, query embeddings fail
            raise RuntimeError("timeout")
        return _keyword_embedder(texts)

    def rerank_down(query, documents, top_n):
        calls["rerank"] += 1
        raise RuntimeError("timeout")

    index = Index(DOCS, embed=embed_index_only, rerank=rerank_down)
    for _ in range(3):
        assert index.search("гарантия П-17/2024")
    assert calls == {"embed": 2, "rerank": 1}
