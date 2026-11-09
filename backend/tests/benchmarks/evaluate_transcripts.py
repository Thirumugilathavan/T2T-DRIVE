"""
Speech Recognition Evaluation Module for T2T DRIVE Benchmarking Suite.
Computes Word Error Rate (WER) and Character Error Rate (CER) with Unicode NFC
normalization for Tamil script and robust token comparison for Tanglish/English.
"""

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

try:
    import jiwer
    HAS_JIWER = True
except ImportError:
    HAS_JIWER = False


def normalize_tamil_text(text: str) -> str:
    """
    Normalizes Tamil Unicode text into canonical NFC form,
    removes punctuation, and collapses multiple whitespace characters.
    """
    if not text:
        return ""

    # Canonical NFC composition (combines base consonant + dependent vowel sign)
    nfc_text = unicodedata.normalize("NFC", text.strip())

    # Remove standard English and Indic punctuation
    cleaned = re.sub(r"[.,\/#!$%\^&\*;:{}=\-_`~()?'\"।॥]", " ", nfc_text)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_speech_text(text: str, language: str = "tanglish") -> str:
    """
    Standardizes speech transcript text for unbiased WER/CER calculation.
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFC", text.strip())

    # For Tamil, keep native characters; for Tanglish/English, case-fold
    if language.lower() in ("ta", "tamil"):
        return normalize_tamil_text(text)

    # Tanglish or English: lowercase and strip punctuation
    lowered = text.lower()
    cleaned = re.sub(r"[.,\/#!$%\^&\*;:{}=\-_`~()?'\"]", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def levenshtein_distance(seq1: List[str], seq2: List[str]) -> int:
    """Standard dynamic programming Levenshtein distance for tokens or characters."""
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = [[0] * size_y for _ in range(size_x)]

    for x in range(size_x):
        matrix[x][0] = x
    for y in range(size_y):
        matrix[0][y] = y

    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x - 1] == seq2[y - 1]:
                matrix[x][y] = matrix[x - 1][y - 1]
            else:
                matrix[x][y] = min(
                    matrix[x - 1][y] + 1,      # deletion
                    matrix[x][y - 1] + 1,      # insertion
                    matrix[x - 1][y - 1] + 1   # substitution
                )
    return matrix[size_x - 1][size_y - 1]


@dataclass
class EvaluationMetric:
    reference: str
    hypothesis: str
    normalized_ref: str
    normalized_hyp: str
    wer: float
    cer: float
    is_perfect_match: bool


class TranscriptEvaluator:
    """
    Evaluates speech recognition output against reference ground truth transcripts.
    """

    def __init__(self):
        self.use_jiwer = HAS_JIWER

    def evaluate_pair(
        self,
        reference: str,
        hypothesis: str,
        language: str = "tanglish"
    ) -> EvaluationMetric:
        """Computes WER and CER for a single reference/hypothesis pair."""
        norm_ref = normalize_speech_text(reference, language=language)
        norm_hyp = normalize_speech_text(hypothesis, language=language)

        if not norm_ref and not norm_hyp:
            return EvaluationMetric(
                reference=reference,
                hypothesis=hypothesis,
                normalized_ref="",
                normalized_hyp="",
                wer=0.0,
                cer=0.0,
                is_perfect_match=True
            )

        if not norm_ref and norm_hyp:
            return EvaluationMetric(
                reference=reference,
                hypothesis=hypothesis,
                normalized_ref="",
                normalized_hyp=norm_hyp,
                wer=1.0,
                cer=1.0,
                is_perfect_match=False
            )

        if norm_ref and not norm_hyp:
            return EvaluationMetric(
                reference=reference,
                hypothesis=norm_hyp,
                normalized_ref=norm_ref,
                normalized_hyp="",
                wer=1.0,
                cer=1.0,
                is_perfect_match=False
            )

        # 1. Word Error Rate (WER)
        ref_words = norm_ref.split()
        hyp_words = norm_hyp.split()

        if self.use_jiwer:
            try:
                wer_val = float(jiwer.wer(norm_ref, norm_hyp))
                cer_val = float(jiwer.cer(norm_ref, norm_hyp))
            except Exception:
                wer_dist = levenshtein_distance(ref_words, hyp_words)
                wer_val = min(1.0, wer_dist / float(max(1, len(ref_words))))
                cer_dist = levenshtein_distance(list(norm_ref), list(norm_hyp))
                cer_val = min(1.0, cer_dist / float(max(1, len(norm_ref))))
        else:
            wer_dist = levenshtein_distance(ref_words, hyp_words)
            wer_val = min(1.0, wer_dist / float(max(1, len(ref_words))))
            cer_dist = levenshtein_distance(list(norm_ref), list(norm_hyp))
            cer_val = min(1.0, cer_dist / float(max(1, len(norm_ref))))

        is_perfect = (norm_ref == norm_hyp)

        return EvaluationMetric(
            reference=reference,
            hypothesis=hypothesis,
            normalized_ref=norm_ref,
            normalized_hyp=norm_hyp,
            wer=round(wer_val, 4),
            cer=round(cer_val, 4),
            is_perfect_match=is_perfect
        )

    def evaluate_batch(
        self,
        pairs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Evaluates a list of records: [{'reference': ..., 'hypothesis': ..., 'language': ...}].
        Returns aggregate metrics, breakdowns, and per-sample results.
        """
        results = []
        total_wer = 0.0
        total_cer = 0.0
        perfect_count = 0

        by_language: Dict[str, Dict[str, float]] = {}
        by_condition: Dict[str, Dict[str, float]] = {}

        for p in pairs:
            ref = p.get("reference", "")
            hyp = p.get("hypothesis", "")
            lang = p.get("language", "tanglish")
            cond = p.get("audio_condition", "UNKNOWN")

            metric = self.evaluate_pair(ref, hyp, language=lang)
            results.append({
                "id": p.get("id"),
                "language": lang,
                "audio_condition": cond,
                **asdict(metric)
            })

            total_wer += metric.wer
            total_cer += metric.cer
            if metric.is_perfect_match:
                perfect_count += 1

            # Accumulate by language
            if lang not in by_language:
                by_language[lang] = {"wer_sum": 0.0, "cer_sum": 0.0, "count": 0}
            by_language[lang]["wer_sum"] += metric.wer
            by_language[lang]["cer_sum"] += metric.cer
            by_language[lang]["count"] += 1

            # Accumulate by condition
            if cond not in by_condition:
                by_condition[cond] = {"wer_sum": 0.0, "cer_sum": 0.0, "count": 0}
            by_condition[cond]["wer_sum"] += metric.wer
            by_condition[cond]["cer_sum"] += metric.cer
            by_condition[cond]["count"] += 1

        n = len(pairs) if pairs else 1
        avg_wer = round(total_wer / n, 4)
        avg_cer = round(total_cer / n, 4)
        accuracy_pct = round((perfect_count / n) * 100.0, 2)

        lang_summary = {}
        for l, stat in by_language.items():
            cnt = max(1, stat["count"])
            lang_summary[l] = {
                "avg_wer": round(stat["wer_sum"] / cnt, 4),
                "avg_cer": round(stat["cer_sum"] / cnt, 4),
                "samples": cnt
            }

        cond_summary = {}
        for c, stat in by_condition.items():
            cnt = max(1, stat["count"])
            cond_summary[c] = {
                "avg_wer": round(stat["wer_sum"] / cnt, 4),
                "avg_cer": round(stat["cer_sum"] / cnt, 4),
                "samples": cnt
            }

        return {
            "total_samples": len(pairs),
            "average_wer": avg_wer,
            "average_cer": avg_cer,
            "exact_match_accuracy_pct": accuracy_pct,
            "breakdown_by_language": lang_summary,
            "breakdown_by_condition": cond_summary,
            "sample_results": results
        }
