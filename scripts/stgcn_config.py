# Apache-2.0 OpenMMLab architecture/preprocessing, based on:
# mmaction2 v1.2.0 configs/skeleton/stgcn/stgcn_8xb16-joint-u100-80e_ntu60-xsub-keypoint-2d.py
# One deterministic clip, as in upstream validation (test uses 10 clips).
default_scope = 'mmaction'
model = dict(type='RecognizerGCN', backbone=dict(type='STGCN', graph_cfg=dict(layout='coco', mode='stgcn_spatial')),
             cls_head=dict(type='GCNHead', num_classes=60, in_channels=256))
test_pipeline = [dict(type='PreNormalize2D'), dict(type='GenSkeFeat', dataset='coco', feats=['j']),
                 dict(type='UniformSampleFrames', clip_len=100, num_clips=1, test_mode=True, seed=255),
                 dict(type='PoseDecode'), dict(type='FormatGCNInput', num_person=2), dict(type='PackActionInputs')]
