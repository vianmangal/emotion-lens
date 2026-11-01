# Project report guide

Use this outline when preparing an academic report for EmotionLens. Describe the
expression classifier and live motion detector separately: they use different
inputs, models and evaluation methods.

## Suggested structure

1. Cover page with project title, authors and faculty details.
2. Contents with page numbers checked after the final export.
3. Abstract describing the implementation, main results and limits.
4. Introduction with the problem statement, objectives and scope.
5. Hardware and software requirements, distinguishing documented prerequisites
   from development recommendations.
6. Existing approaches and their limitations.
7. Developed model, including architecture, modules and implementation.
8. Results and discussion with clearly attributed metrics and screenshots.
9. Conclusion, project limitations and future enhancements.
10. References and an appendix of short source-code excerpts.

For the supplied academic format, use Times New Roman with 14-point headings and
12-point body text. Keep figures readable at the final printed size.

## Sources to consult

- [Project overview and local setup](../README.md)
- [Expression network](../src/model.py)
- [Expression preprocessing](../src/preprocess.py)
- [Expression evaluation script](../src/evaluate.py)
- [Current visual detector](VISUAL_STRIKE_MODEL.md)
- [Verification history](SAFETY_EVALUATION.md)
- [Historical deployment architecture](DEPLOY_AWS.md)

Record the repository revision and date used for the report. Hosting status can
change independently of source documentation; describe historical deployment
details as historical and date any live availability check.

## Evidence and interpretation

Distinguish saved evaluation results, software tests, service-readiness checks and
individual demonstrations. A health response does not establish model accuracy.
A screenshot of a prediction is evidence of that displayed output, rather than
an additional dataset-level accuracy measurement.

Retain the interface wording "Possible hit detected" in captions. Do not describe
an experimental motion warning as confirmed contact, harmful intent or injury.
Likewise, expression outputs classify facial appearance and do not establish a
person's internal emotional state.

## Final review

- Check that tables match their source artifacts and identify the model version.
- Label each figure, explain its state and preserve readable scores or status text.
- Update contents and references after inserting figures.
- Render the final PDF and inspect every page for clipping and page-break errors.
- Keep private photographs, credentials and local runtime data out of source
  control unless there is explicit permission to publish them.
