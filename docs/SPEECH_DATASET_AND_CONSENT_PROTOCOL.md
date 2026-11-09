# T2T DRIVE — Consensual Speech Dataset Collection & Research Protocol
## Field Acoustic Data Gathering for Low-Resource Auto-Rickshaw Speech Recognition

### 1. Research Purpose & Objectives
Commercial speech recognition engines degrade significantly in Indian auto-rickshaws due to high SPL (Sound Pressure Level) background noise (engine vibration, horn cacophony, wet monsoon tires) combined with regional code-mixing (Tamil-English / Tanglish).

This protocol defines the ethical, technical, and regulatory procedures for collecting in-situ multi-channel audio datasets with explicit consent from drivers and passengers for speech model fine-tuning and benchmark evaluation.

---

### 2. Ethical Principles & Informed Consent Framework

1. **Prior Informed Consent:**
   - Both driver and passenger must provide affirmative, documented consent prior to any audio recording.
   - Recording must never be conducted covertly or under false pretenses.
2. **Right to Immediate Withdrawal & Purge:**
   - Participants may halt recording at any time without forfeiture of research honorarium.
   - Upon withdrawal, all audio captured during that session is purged immediately in the participant's presence.
3. **Fair Compensation / Honorarium:**
   - Drivers: ₹500 per 1-hour recording session + ₹150 fuel allowance.
   - Passengers: ₹300 per 30-minute simulated commute session.

---

### 3. Participant Consent Scripts

#### Script A: Driver Consent (Tamil / தமிழ்)
> *"வணக்கம் ஐயா/அம்மா. T2T DRIVE ஆராய்ச்சி திட்டத்திற்காக வண்டியின் இரைச்சல் மற்றும் சவாரி உரையாடல்களை ஒலிப்பதிவு செய்ய உங்கள் அனுமதியை கேட்கிறோம். இந்த ஒலிப்பதிவு கணினி குரல் அறிதல் திறனை மேம்படுத்த மட்டுமே பயன்படுத்தப்படும். உங்கள் பெயர் அல்லது தனிப்பட்ட விவரங்கள் வெளியிடப்படாது. நீங்கள் எப்போது வேண்டுமானாலும் இந்த பதிவை நிறுத்தலாம். இதற்கு நீங்கள் சம்மதிக்கிறீர்களா?"*

#### Script B: Driver Consent (English)
> *"Hello. For the T2T DRIVE research study, we request your permission to record in-cabin audio during your trip to train noise-aware voice recognition models for auto-rickshaws. No personal identifying information will be shared. You have the right to withdraw at any moment. Do you consent to participate?"*

#### Script C: Passenger Consent (Tamil / தமிழ்)
> *"வணக்கம். இந்த சவாரியின் போது பாதை மற்றும் கட்டணம் தொடர்பான குரல் அறிதல் சோதனையை நடத்துகிறோம். உரையாடல்கள் ரகசியமாக வைக்கப்படும். தனிப்பட்ட பேச்சு எதுவும் சேமிக்கப்படாது. இதற்கு உங்கள் அனுமதி உண்டா?"*

---

### 4. Acoustic Target Scenarios & Environmental Matrix

To train robust acoustic models, data collection must systematically span four distinct in-cabin acoustic profiles:

| Profile Code | Operating Condition | Speed Range | Background Noise Characteristics | Typical SNR | Target Minutes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ENV-01** | Stationary / Engine Off | 0 km/h | Quiet parking, light street murmur | +15 dB to +22 dB | 60 mins |
| **ENV-02** | Stationary / Engine Idling | 0 km/h | 2-stroke / 4-stroke low-frequency thrum (120–400 Hz) | +5 dB to +12 dB | 90 mins |
| **ENV-03** | Urban Stop-and-Go | 10–35 km/h | Horn honks (2.5–4.5 kHz), gear changes, braking squeal | 0 dB to +6 dB | 120 mins |
| **ENV-04** | High-Speed Flyover / Monsoon | 40–55 km/h | Severe wind buffeting, tire spray on wet asphalt, rain on canopy | -6 dB to +2 dB | 90 mins |

---

### 5. Multi-Microphone Rig & Recording Hardware Setup
1. **Primary Driver Sensor:** Dual-array directional electret microphone mounted on the steering column / meter cluster (cardioid pattern directed at driver).
2. **Passenger Ambient Sensor:** Boundary condenser microphone mounted on the central roof bar between front and passenger seats.
3. **Reference Noise Channel:** Omnidirectional microphone mounted in the under-seat engine compartment (used to capture ground-truth noise for Wiener filter training).
4. **Recording Interface:** Zoom H6 or Zoom F6 32-bit float audio recorder at 48,000 Hz 24-bit linear PCM (downsampled to 16,000 Hz for ASR training).

---

### 6. PII De-Identification & Data Scrubbing Protocol
1. **Automated Named Entity Redaction:**
   - Any audio segments containing phone numbers (10-digit strings), Aadhaar numbers, full personal names, or home addresses are flagged by dual acoustic NER pipelines.
2. **Manual Ear-Audit Quality Check:**
   - Research assistants listen to flagged segments and replace PII audio with synthetic pink noise bursts.
3. **Cryptographic Pseudonymization:**
   - Recordings are labeled solely by anonymous UUIDs (e.g. `REC_SALEM_20261109_001_ENV03.wav`).
   - Cross-reference mapping keys linking UUIDs to participant consent forms are stored on an encrypted, air-gapped drive accessible only by the Principal Investigator.

---

### 7. Dataset Packaging & Distribution Format
The resulting open benchmark corpus is organized as follows:
```text
t2t-drive-speech-corpus/
├── audio/
│   ├── ENV01/
│   │   ├── SESS_001_CH0_DRIVER.wav
│   │   └── SESS_001_CH1_CABIN.wav
│   └── ENV04/
├── transcripts/
│   ├── SESS_001.json  # Utterance timestamps, language (ta/ta-en/en), intent annotations
├── metadata.csv       # SNR (dB), RPM estimate, speed (km/h), weather conditions
└── LICENSE            # CC-BY-NC 4.0 Academic Research License
```
