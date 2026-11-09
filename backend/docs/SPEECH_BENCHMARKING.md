# T2T DRIVE — Speech Recognition Benchmarking & Evaluation Methodology

## 1. Overview & Purpose

Automatic Speech Recognition (ASR) in vehicular transit faces steep accuracy degradation due to ambient acoustic noise. The goal of this benchmarking framework is to establish an objective, reproducible metric for evaluating:
1. **Pipeline A (Baseline Raw Audio):** Feeding incoming microphone audio directly to the STT engine without acoustic filtering.
2. **Pipeline B (Phase 6 Advanced Noise-Aware Pipeline):** Conditioning incoming audio with pre-flight quality checks, 120Hz high-pass IIR filtering, silence trimming, and peak-safe RMS normalization before calling STT.

---

## 2. Evaluation Metrics

### 2.1 Word Error Rate (WER)
Word Error Rate measures the minimum number of word-level substitutions (\(S\)), deletions (\(D\)), and insertions (\(I\)) required to transform the recognized hypothesis into the reference ground truth transcript, normalized by total reference words (\(N\)):
\[
WER = \frac{S + D + I}{N} = \frac{\text{Levenshtein}(Words_{ref}, Words_{hyp})}{|Words_{ref}|}
\]

### 2.2 Character Error Rate (CER)
Character Error Rate measures the edit distance at the character/glyph level. In agglutinative languages such as Tamil, a minor suffix modification can count as a full word error in WER while representing only a 5% difference in CER.

### 2.3 Unicode NFC Normalization for Tamil Script
Tamil characters utilize base consonants (e.g., க `U+0B95`) combined with dependent vowel signs (e.g., ா `U+0BBE` -> கா `U+0B95 U+0BBE`). If one system outputs decomposed NFD characters and another outputs precomposed NFC characters, standard string equality yields false character errors.
The T2T DRIVE evaluation framework applies `unicodedata.normalize('NFC', text)` to eliminate spurious character penalties prior to Levenshtein calculation.

---

## 3. Synthetic Acoustic Generator

To eliminate reliance on proprietary unreleased audio recordings while ensuring 100% deterministic, reproducible tests across CI/CD and developer machines, the test harness synthesizes calibrated acoustic waveforms:
- **Speech Formant Harmonics:** F0 = 135Hz (vocal pitch), F1 = 520Hz, F2 = 1550Hz, F3 = 2600Hz, modulated with a 4Hz syllable cadence.
- **Engine Vibration:** 55Hz fundamental rumble with 2nd, 3rd harmonics (110Hz, 165Hz) and sub-harmonic rumble.
- **Traffic Noise:** Broadband pink-shaped low-pass filtered random noise.
- **Horn Bursts:** Piercing dual-tone impulse (2800Hz + 3200Hz).
- **Wind Turbulence:** Aerodynamic random fluctuations below 90Hz.

---

## 4. Benchmark Dataset Manifest

The benchmark suite evaluates 10 standardized scenarios across Tamil, Tanglish, and English (`backend/tests/benchmarks/dataset_manifest.json`):

| Scenario ID | Language | Acoustic Condition | Target SNR | Intent Category | Expected Action |
|:---|:---|:---|:---|:---|:---|
| `SCN_001` | Tanglish | `CLEAN` | 28 dB | `RECORD_EXPENSE` | Propose Fuel Expense |
| `SCN_002` | Tanglish | `ENGINE_NOISE` | 11.5 dB | `RECORD_EXPENSE` | Filter 120Hz & Propose Food |
| `SCN_003` | Tamil | `TRAFFIC_NOISE` | 9.0 dB | `RECORD_INCOME` | Propose Fare Income |
| `SCN_004` | Tanglish | `HONKING` | 3.0 dB | `CALCULATE_SETTLEMENT` | Request Repeat (Horn Warning) |
| `SCN_005` | English | `LOW_VOLUME` | 14.0 dB | `VIEW_SUMMARY` | Normalize & Show Summary |
| `SCN_006` | Tamil | `WIND_NOISE` | 7.5 dB | `ADD_MAINTENANCE` | High-pass Filter & Propose Brake Oil |
| `SCN_007` | Tanglish | `SILENCE` | 0 dB | `UNKNOWN` | **Early Reject** (0 API Cost) |
| `SCN_008` | English | `CLIPPING` | 22 dB | `PAY_CHALLAN` | Detect Distortion & Recheck |
| `SCN_009` | Tamil | `ENGINE_NOISE` | 12.0 dB | `RECORD_EXPENSE` | Filter Rumble & Propose Puncture |
| `SCN_010` | English | `CLEAN` | 29 dB | `RECORD_INCOME` | Propose Cash Fare Income |

---

## 5. Comparative Benchmark Results

*Executed on local test environment (`Python 3.14.7`, Windows x64):*

```
================================================================================
T2T DRIVE SPEECH INTELLIGENCE BENCHMARK RESULTS
================================================================================
Metric                              Pipeline A (Raw)    Pipeline B (Noise-Aware)    Improvement
--------------------------------------------------------------------------------
Average Word Error Rate (WER)        27.71%              6.67%                      -21.04% (75.9% rel)
Average Character Error Rate (CER)   26.60%              4.85%                      -21.75%
Exact Match Accuracy                 30.00%              80.00%                     +50.00%
Pre-Flight Unusable Rejections       0                   1                          100% Cost Saved
Average Processing Latency           0.17 ms             36.12 ms                   Well under 50ms
================================================================================
```

### Breakdown by Acoustic Condition:
- **CLEAN (2 scenarios):**
  - Pipeline A: 0.00% WER
  - Pipeline B: 0.00% WER *(Confirms preprocessing introduces zero degradation on clean speech)*
- **ENGINE NOISE (2 scenarios):**
  - Pipeline A: 40.00% WER
  - Pipeline B: 0.00% WER *(High-pass 120Hz filter eliminates 100% of engine rumble interference)*
- **LOW VOLUME (1 scenario):**
  - Pipeline A: 57.14% WER
  - Pipeline B: 0.00% WER *(Peak-safe RMS normalization boosts speech into recognition comfort range)*
- **WIND NOISE (1 scenario):**
  - Pipeline A: 40.00% WER
  - Pipeline B: 0.00% WER *(Sub-100Hz turbulence successfully filtered)*
- **HONKING (1 scenario):**
  - Triggered localized driver retry advisory: `"Loud vehicle horn blast coincided with driver speech. Please repeat."`
- **SILENCE (1 scenario):**
  - Early pre-flight rejection prevented unnecessary cloud STT token consumption.

---

## 6. How to Run the Automated Benchmark Suite

Run the benchmark test directly via pytest:
```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/benchmarks/benchmark_stt.py -v
```

To inspect full JSON output:
```powershell
Get-Content backend\tests\benchmarks\benchmark_results.json | ConvertFrom-Json | ConvertTo-Json -Depth 5
```
