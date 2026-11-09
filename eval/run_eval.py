"""Local evaluation: retrieval quality always, answer quality when the API is configured.

    python -m eval.run_eval                 # retrieval only, no API calls
    python -m eval.run_eval --answers       # + answers, latency and LLM grading against golden

Answer grading uses the same model as a judge, so treat the score as a relative
signal between runs, not as the platform score.
"""

import argparse
import csv
import json
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import config
import guard
import kb
import llm
from answer import answer, prepare
from search import Index

ROOT = Path(__file__).resolve().parent
PLATFORM_QUESTIONS = 300  # rough size of the hidden set, for the time projection

JUDGE = """Ты проверяешь ответ юридического ассистента по эталонному ответу.
Шкала:
1.0 — по сути совпадает с эталоном, ссылки на пункты и статьи верные;
0.75 — верно по сути, мелкие неточности или лишние детали;
0.5 — частично верно, упущено существенное;
0.25 — в основном неверно;
0.0 — неверно, или содержит факт, число, норму или ссылку, которых нет в эталоне и которые ему противоречат.
Отказ при наличии ответа в эталоне — 0.0. Отказ, когда эталон тоже сообщает об отсутствии данных, — 1.0.
Верни только JSON: {"score": <число из шкалы>, "reason": "<одно предложение>"}"""

SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)


def load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def retrieval_metrics(index: Index, case: dict) -> dict:
    """covered: every number and reference of the golden answer is present in what the model sees."""
    expected = [e for e in case["expected_docs"].split(";") if e]
    blocks, messages = prepare(index, case["question"])
    titles = [b.doc.title for b in blocks]
    return {
        "hit1": (any(e in titles[0] for e in expected) if titles else False) if expected else None,
        "recall": all(any(e in t for t in titles) for e in expected) if expected else None,
        "covered": not guard.check(case["golden"], messages[-1]["content"]),
        "context_chars": sum(len(b.text) for b in blocks),
    }


def judge(question: str, golden: str, candidate: str) -> tuple[float | None, str]:
    content = f"Вопрос:\n{question}\n\nЭталон:\n{golden}\n\nОтвет кандидата:\n{candidate}"
    try:
        reply = llm.chat([{"role": "system", "content": JUDGE}, {"role": "user", "content": content}])
        verdict = json.loads(re.search(r"\{.*\}", reply, re.DOTALL).group())
        score = min(SCORES, key=lambda s: abs(s - float(verdict["score"])))
        return score, str(verdict.get("reason", ""))
    except (llm.LLMError, AttributeError, ValueError, KeyError, TypeError) as exc:
        return None, f"judge failed: {type(exc).__name__}"


def answer_metrics(index: Index, case: dict) -> dict:
    started = time.monotonic()
    try:
        result = answer(index, case["question"])
    except Exception as exc:  # one broken case must not abort the run
        return {"answer": "", "seconds": time.monotonic() - started, "score": None, "reason": type(exc).__name__}
    seconds = time.monotonic() - started
    score, reason = judge(case["question"], case["golden"], result.text)
    return {
        "answer": result.text,
        "seconds": seconds,
        "retried": result.retried,
        "dropped": ";".join(result.dropped),
        "score": score,
        "reason": reason,
    }


def _mean(values: list) -> str:
    present = [float(v) for v in values if v is not None]
    return f"{statistics.mean(present):.3f} (n={len(present)})" if present else "n/a"


def summarize(rows: list[dict], with_answers: bool) -> None:
    print(f"hit@1:          {_mean([r['hit1'] for r in rows])}")
    print(f"recall:         {_mean([r['recall'] for r in rows])}")
    print(f"golden covered: {_mean([r['covered'] for r in rows])}")
    print(f"context chars:  {_mean([r['context_chars'] for r in rows])}")
    if not with_answers:
        return
    seconds = [r["seconds"] for r in rows]
    print(f"judge score:    {_mean([r['score'] for r in rows])}")
    for category in sorted({r["category"] for r in rows}):
        print(f"  {category:14} {_mean([r['score'] for r in rows if r['category'] == category])}")
    print(f"zero scores:    {sum(1 for r in rows if r['score'] == 0.0)}")
    print(f"retried:        {sum(1 for r in rows if r.get('retried'))}")
    print(f"facts dropped:  {sum(1 for r in rows if r.get('dropped'))}")
    print(f"latency p50/max: {statistics.median(seconds):.1f}s / {max(seconds):.1f}s")
    projected = statistics.mean(seconds) * PLATFORM_QUESTIONS / config.MAX_WORKERS
    print(f"projected {PLATFORM_QUESTIONS} questions at {config.MAX_WORKERS} workers: {projected / 60:.1f} min")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.csv")
    parser.add_argument("--kb", type=Path, default=ROOT.parent / "data/raw/knowledge-base.zip")
    parser.add_argument("--answers", action="store_true", help="generate and grade answers (needs API)")
    parser.add_argument("--lexical", action="store_true", help="disable dense search and reranking")
    args = parser.parse_args()

    use_api = bool(config.API_BASE and config.API_KEY) and not args.lexical
    if args.answers and not (config.API_BASE and config.API_KEY):
        parser.error("--answers needs LLM_BASE_URL and LLM_API_KEY")
    started = time.monotonic()
    index = Index(kb.load_zip(args.kb), embed=llm.embed if use_api else None, rerank=llm.rerank if use_api else None)
    print(
        f"index: {len(index.chunks)} chunks, dense={'on' if index.vectors is not None else 'off'}, "
        f"built in {time.monotonic() - started:.1f}s"
    )

    cases = load_cases(args.cases)
    rows = [{"id": c["id"], "category": c["category"], **retrieval_metrics(index, c)} for c in cases]
    if args.answers:
        with ThreadPoolExecutor(config.MAX_WORKERS) as pool:
            for row, result in zip(rows, pool.map(lambda c: answer_metrics(index, c), cases), strict=True):
                row.update(result)

    for row in rows:
        score = "" if row.get("score") is None else f" score={row['score']}"
        print(f"{row['id']:>15} hit1={row['hit1']} recall={row['recall']} covered={row['covered']}{score}")
    summarize(rows, args.answers)

    out = ROOT / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved {out.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
