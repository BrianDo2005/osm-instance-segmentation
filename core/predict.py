import os
import sys
import glob
from mask_rcnn import model as modellib
from core.mask_rcnn_config import MyMaskRcnnConfig, TEST_DATA_DIR
from core.utils import georeference, rectangularize, get_contours, get_contour
from typing import Iterable, Tuple, List
from PIL import Image
from core.settings import IMAGE_WIDTH
import numpy as np
import json


class Predictor:
    config = MyMaskRcnnConfig()

    class InferenceConfig(config.__class__):
        # Run detection on one image at a time
        GPU_COUNT = 1
        IMAGES_PER_GPU = 1
        IMAGE_MIN_DIM = 320
        IMAGE_MAX_DIM = 320

    def __init__(self, weights_path: str):
        if not os.path.isfile(weights_path):
            raise RuntimeError("Weights cannot be found at: {}".format(weights_path))
        self.weights_path = weights_path
        self._model = None

    def predict_array(self, img_data: np.ndarray, extent=None, do_rectangularization=True, tile=None) \
            -> List[List[Tuple[int, int]]]:
        if not tile:
            tile = (0, 0)

        if not self._model:
            print("Loading model")
            inference_config = self.InferenceConfig()
            # Create model in training mode
            model = modellib.MaskRCNN(mode="inference", config=inference_config, model_dir="log")
            model.load_weights(self.weights_path, by_name=True)
            self._model = model

        model = self._model
        print("Predicting...")
        res = model.detect([img_data], verbose=1)
        print("Prediction done")
        print("Extracting contours...")
        point_sets = []
        masks = res[0]['masks']
        for i in range(masks.shape[-1]):
            mask = masks[:, :, i]
            points = get_contour(mask)
            score = res[0]['scores'][i]
            point_sets.append((list(points), score))
        print("Contours extracted")

        rectangularized_outlines = []
        if do_rectangularization:
            point_sets = list(map(lambda point_set_with_score: (rectangularize(point_set_with_score[0]), point_set_with_score[1]), point_sets))

        point_sets_mapped = []
        col, row = tile
        for points, score in point_sets:
            pp = list(map(lambda p: (p[0]+col*256, p[1]+row*256), points))
            if pp:
                point_sets_mapped.append((pp, score))
        point_sets = point_sets_mapped

        if not extent:
            rectangularized_outlines = point_sets
        else:
            for o, score in point_sets:
                georeffed = georeference(o, extent)
                if georeffed:
                    rectangularized_outlines.append((georeffed, score))
        return rectangularized_outlines

    def predict_path(self, img_path: str, extent=None) -> List[List[Tuple[int, int]]]:
        img = Image.open(img_path)
        data = np.asarray(img, dtype="uint8")
        return self.predict_array(img_data=data, extent=extent)


def test_all():
    predictor = Predictor(os.path.join(os.getcwd(), "model", "stage2.h5"))
    images = glob.glob(os.path.join(TEST_DATA_DIR, "**/*.jpg"), recursive=True)
    annotations = []
    progress = 0
    nr_images = float(len(images))
    for idx, img_path in enumerate(images):
        point_sets_with_score = predictor.predict_path(img_path)
        for contour, score in point_sets_with_score:
            xs = list(map(lambda pt: pt[0], contour))
            ys = list(map(lambda pt: pt[1], contour))
            if contour:
                bbox = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            else:
                bbox = []
            ann = {
                "image_id": int(os.path.basename(img_path).replace(".jpg", "")),
                "category_id": 100,
                "segmentation": [contour],
                "bbox": bbox,
                "score": score
            }
            annotations.append(ann)
        new_progress = 100*idx / nr_images
        if new_progress > progress:
            progress = new_progress
            print("Progress: {}%".format(progress))
            sys.stdout.flush()
    with open("predictions.json", "w") as fp:
        fp.write(json.dumps(annotations))


if __name__ == "__main__":
    test_all()
