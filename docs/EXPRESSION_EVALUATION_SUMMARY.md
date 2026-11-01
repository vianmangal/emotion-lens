# Saved expression evaluation summary

This page makes the retained expression results easier to cite in a project
report. It summarizes the existing artifact rather than reporting a new run.

## Artifact and results

Model artifact family: `emotion_cnn_20260530_193721`.

Sources:

- [Classification report](../models/emotion_cnn_20260530_193721_classification_report.txt)
- [Confusion matrix](../models/emotion_cnn_20260530_193721_confusion_matrix.png)
- [Evaluation implementation](../src/evaluate.py)

| Class | Precision | Recall | F1 score | Support |
| --- | ---: | ---: | ---: | ---: |
| angry | 0.5639 | 0.5438 | 0.5537 | 958 |
| fear | 0.4874 | 0.4717 | 0.4794 | 1024 |
| happy | 0.8850 | 0.8112 | 0.8465 | 1774 |
| neutral | 0.5501 | 0.6237 | 0.5846 | 1233 |
| sad | 0.4780 | 0.4972 | 0.4874 | 1247 |
| Macro average | 0.5929 | 0.5895 | 0.5903 | 6236 |
| Weighted average | 0.6228 | 0.6145 | 0.6176 | 6236 |

Overall accuracy is **0.6145 (61.45%)** over **6236 images**. Values above retain
the four-decimal rounding of the source report.

## How to interpret the table

Precision measures correctness among predictions assigned to a class. Recall
measures coverage of the true examples of that class. F1 balances precision and
recall; support is the evaluated class count.

The happy class has the highest reported F1 score. Fear and sad have F1 scores
below 0.50. Include class-level results alongside overall accuracy so this uneven
performance remains visible. The macro average weights classes equally; the
weighted average uses their support counts.

These are expression-image metrics, not live action-recognition metrics. They do
not establish a person's internal emotions or the reliability of a possible-hit
warning. For video evaluation, use the separate
[visual detector report](VISUAL_STRIKE_MODEL.md).

## Repeating an evaluation

With the optional TensorFlow environment and dataset installed, select an explicit
model and matching label map instead of relying on newest-file discovery:

```bash
python src/evaluate.py \
  --model-path models/emotion_cnn_20260530_193721.keras \
  --labels-path models/emotion_cnn_20260530_193721_labels.json \
  --test-dir data/fer2013/test
```

Run this in a separate checkout if the retained evaluation artifacts must remain
unchanged: the script writes report and image files using the model's basename.
Record the data provenance, model revision and environment with any new result.
Dataset files are not included by this documentation change.
