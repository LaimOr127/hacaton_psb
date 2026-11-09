"""Platform entry point: questions.csv + knowledge-base.zip -> submission.csv."""

import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
import kb
from answer import FALLBACK, answer
from search import Index

OUTPUT = Path("submission.csv")
KB_NAMES = ("knowledge-base.zip", "knowledge_base.zip", "kb.zip")
TIMEOUT_ANSWER = "Не удалось сформировать ответ по базе знаний в отведённое время. Повторите запрос."
SAVE_EVERY = 10


def find_file(*names: str) -> Path:
    roots = (config.DATA_DIR, Path(__file__).resolve().parent / config.DATA_DIR, Path.cwd())
    for root in roots:
        for name in names:
            if (root / name).is_file():
                return root / name
    raise FileNotFoundError("not found: " + ", ".join(names))


def load_questions(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"id", "question"} <= set(reader.fieldnames):
            raise ValueError("questions.csv must have columns id,question")
        rows = [(str(r["id"]).strip(), str(r["question"] or "").strip()) for r in reader]
    seen: set[str] = set()
    unique = []
    for qid, question in rows:
        if qid and qid not in seen:
            seen.add(qid)
            unique.append((qid, question))
    return unique


def write_submission(ids: list[str], answers: dict[str, str]) -> None:
    """Atomic write: a timeout kill never leaves a half-written file."""
    tmp = OUTPUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["id", "answer"])
        for qid in ids:
            writer.writerow([qid, answers.get(qid) or FALLBACK])
    os.replace(tmp, OUTPUT)


def main() -> None:
    started = time.monotonic()
    deadline = started + config.TIME_BUDGET_SECONDS
    questions = load_questions(find_file("questions.csv"))
    ids = [qid for qid, _ in questions]
    answers: dict[str, str] = {}
    write_submission(ids, answers)

    index = Index(kb.load_zip(find_file(*KB_NAMES)))
    print(f"questions={len(questions)} chunks={len(index.chunks)}", flush=True)

    def work(qid: str, question: str) -> tuple[str, str]:
        if time.monotonic() > deadline:
            return qid, TIMEOUT_ANSWER
        if not question:
            return qid, "Вопрос не задан. Сформулируйте вопрос по документам базы знаний."
        try:
            return qid, answer(index, question).text
        except Exception as exc:  # one bad question must not lose the whole run
            print(f"question {qid}: {type(exc).__name__}", file=sys.stderr)
            return qid, FALLBACK

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = [pool.submit(work, qid, question) for qid, question in questions]
        for done, future in enumerate(as_completed(futures), 1):
            qid, text = future.result()
            answers[qid] = text
            if done % SAVE_EVERY == 0:
                write_submission(ids, answers)
                print(f"{done}/{len(questions)} in {time.monotonic() - started:.0f}s", flush=True)

    write_submission(ids, answers)
    print(f"submission.csv: {len(answers)} answers in {time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
