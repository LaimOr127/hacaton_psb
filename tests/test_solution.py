import csv
import zipfile

import pytest

import config
import solution
from answer import FALLBACK


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    with (data / "questions.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "question"])
        writer.writerow(["1", "Какая арендная плата?"])
        writer.writerow(["2", "Пользователь: Привет\nАссистент: Здравствуйте\nПользователь: Срок?"])
    with zipfile.ZipFile(data / "knowledge-base.zip", "w") as archive:
        archive.writestr("документы__Договор.txt", "ДОГОВОР\n3. Плата\n3.1. Арендная плата 450 000 рублей.\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", data)
    return tmp_path


def _read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_answers_with_csv_special_characters_round_trip(workspace, monkeypatch):
    tricky = 'Плата — 450 000 рублей, "включая НДС"\n(п. 3.1).'
    monkeypatch.setattr(solution, "answer", lambda index, q: type("A", (), {"text": tricky})())
    solution.main()
    rows = _read(workspace / "submission.csv")
    assert [r["id"] for r in rows] == ["1", "2"]
    assert all(r["answer"] == tricky for r in rows)


def test_llm_failure_still_produces_full_file(workspace, monkeypatch):
    def broken(index, question):
        raise RuntimeError("proxy down")

    monkeypatch.setattr(solution, "answer", broken)
    solution.main()
    rows = _read(workspace / "submission.csv")
    assert len(rows) == 2
    assert all(r["answer"] == FALLBACK for r in rows)


def test_duplicate_ids_are_answered_once(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text('id,question\n1,"a"\n1,"b"\n2,"c"\n', encoding="utf-8")
    assert solution.load_questions(path) == [("1", "a"), ("2", "c")]
