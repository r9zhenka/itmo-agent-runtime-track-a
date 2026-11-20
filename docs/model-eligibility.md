# First checkpoint-2 model

Verified on **2026-11-19**. The first pair is the repository's custom harness with
`deepseek-ai/DeepSeek-V4.1-Flash-1017`, served through the course's OpenAI-compatible
endpoint `https://litellm-backend.deeppavlov.ai/v1`. Credentials stay in the server's
ignored `.env`; the model receives no provider key.

The course's `projects/README.md`, section 0-1, explicitly permits DeepSeek 4.1 /
4.0 Flash. The version suffix corresponds to the
[official October 17 release](https://api-docs.deepseek.com/news/news261017/).
The provider's model listing and a successful live tool-using request confirmed
the configured model identifier. This identifies the served model, not an
independent verification of the provider's underlying weights.

[Artificial Analysis](https://artificialanalysis.ai/models/deepseek-v4-1-flash-1017)
reports Intelligence Index **33** for its **Max** variant, using index **v5.0.1**.
Its [release overview](https://artificialanalysis.ai/models/releases) shows a
**19–33** range across three effort levels. These figures must not be mixed with
older index versions. Our campaign leaves reasoning effort at the course
provider's default; we have not established that this is the AA Max setting, so
33 is a reference value for that evaluated variant, not a claimed score for our
endpoint configuration.

The campaign fixes `max_tokens=2048`, 16 agent steps, a 90-second provider timeout,
a 600-second run deadline, three concurrent sessions and three repetitions per
task. Provider defaults otherwise remain unchanged. Source hashes and parameters
are saved before the run in `results/cp2-manifest.json`.

One pair establishes a checkpoint-2 baseline. It does not justify a comparative
winner: additional eligible pairs, a fixed environment and the basis/composite
analysis remain checkpoint-3 work.
