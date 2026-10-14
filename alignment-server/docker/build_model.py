"""Build the same pinned multilingual int8 model; only runs during image build."""

import os

import torch
from ctranslate2.converters import TransformersConverter
from transformers import AutoTokenizer


torch.set_num_threads(2)
model = os.environ["MODEL_ID"]
revision = os.environ["MODEL_REVISION"]
destination = "/model"
TransformersConverter(model, revision=revision).convert(destination, quantization="int8")
AutoTokenizer.from_pretrained(model, revision=revision).save_pretrained(destination)
