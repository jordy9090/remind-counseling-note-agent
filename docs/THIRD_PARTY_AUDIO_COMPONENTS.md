# Third-Party Audio Components

This project installs the following audio runtime only through the optional `audio-whisperx` dependency group. Model files are downloaded by their upstream libraries at runtime and are not stored in this repository.

## Components

| Component | Role | License and official source |
| --- | --- | --- |
| WhisperX 3.8.6 | ASR orchestration, forced alignment, and speaker assignment | BSD-2-Clause. [WhisperX v3.8.6 license](https://github.com/m-bain/whisperX/blob/v3.8.6/LICENSE) |
| OpenAI Whisper | Upstream speech-recognition model and code lineage used by WhisperX | MIT. [OpenAI Whisper license](https://github.com/openai/whisper/blob/main/LICENSE) |
| `kresnik/wav2vec2-large-xlsr-korean` | Korean forced-alignment model for Whisper transcript word timestamps | Apache-2.0. [Model card](https://huggingface.co/kresnik/wav2vec2-large-xlsr-korean), [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) |
| Zeroth-Korean dataset | Training dataset identified by the Korean alignment model card | CC BY 4.0. [Dataset card and attribution](https://huggingface.co/datasets/kresnik/zeroth_korean), [CC BY 4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode) |
| `pyannote/speaker-diarization-community-1` | Local speaker diarization used through WhisperX | CC BY 4.0. [Model card, conditions, and attribution](https://huggingface.co/pyannote/speaker-diarization-community-1), [CC BY 4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode) |

## Use Conditions and Notices

- Review each upstream license and model card before deployment or redistribution. This document is an inventory, not legal advice or a substitute for the license text.
- Preserve the complete upstream copyright, attribution, license, and notice files when redistribution requires them. Do not replace required notices with this summary.
- The Community-1 model is gated on Hugging Face. An authorized user must accept the model conditions and provide a read token through the host environment before download.
- Keep model and dataset attribution links with deployment documentation when required by the applicable license.
- Do not commit Hugging Face tokens, downloaded model caches, or model weights to this repository.
