# Capturing demonstration evidence

Use screenshots to document observable application behavior. Keep them separate
from the aggregate results in the
[expression summary](EXPRESSION_EVALUATION_SUMMARY.md) and
[visual model report](VISUAL_STRIKE_MODEL.md).

## Before a demonstration

Follow the [local setup instructions](LOCAL_SETUP.md), check model readiness and
keep phone alerts disabled. Do not enable owner or demo calling just to capture a
screenshot. Obtain permission from everyone pictured before publishing images.
Never include owner keys, provider credentials or private contact details.

Record the capture date, application URL or local address, source revision when
known, model identifier and whether the image shows an input, a returned result
or a monitoring state. A deployment health response is readiness evidence, not an
accuracy measurement.

## Expression analysis

1. Select Upload Image or capture a Webcam Snapshot.
2. Use a permitted image that satisfies the displayed size and format limits.
3. Submit it for analysis and wait for the returned result.
4. Capture the analysis frame, face box, dominant label, score distribution and
   model identifier together.

Transcribe displayed percentages exactly. A caption such as "Happy displayed at
73.6% for this input" reports the visible output. It does not mean 73.6% test-set
accuracy or prove the subject's emotional state. A second example can show a
different input and score distribution without implying a new benchmark.

## Live Safety

1. Leave calls disabled, start the camera and frame two consenting participants.
2. Wait for clear tracking and sufficient video history before demonstrating.
3. Use staged movements with separation and no physical contact.
4. Capture the person boxes, status banner and rate indicators together.
5. Stop the camera after the demonstration.

Preserve the exact warning "Possible hit detected". Person numbers are temporary
session track IDs. Camera FPS and tracking FPS describe different pipeline stages;
neither is the action classifier's inference rate. A still image cannot verify
the complete movement sequence, physical contact, intent or alert accuracy.

## Trial panel and evaluation

An empty trial panel documents available controls, not measured performance. For
an actual trial series, include both staged attempts and ordinary gestures,
record unscored trials, swap roles and export the results before reset or reload.
See the [demo guide](DEMO.md) for the workflow and
[export interpretation](DETECTION_QUALITY.md) for limitations.

Do not compute recall or precision from a few selected screenshots. Preserve trial
counts, labels, timing and conditions, and distinguish development replay from
independent participant-based webcam validation.
