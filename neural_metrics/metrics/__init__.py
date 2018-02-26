import argparse
import logging
import os
import sys
from collections import OrderedDict
from enum import Enum, auto

from neural_metrics import models
from neural_metrics.metrics.anatomy import combine_graph, score_edge_ratio, model_graph
from neural_metrics.metrics.physiology.mapping import physiology_mapping, get_mapped_layers
from neural_metrics.models import model_name_from_activations_filepath
from neural_metrics.utils import StorageCache

_logger = logging.getLogger(__name__)


def score_anatomy(model, region_layers):
    _model_graph = model_graph(model, layers=list(region_layers.values()))
    _model_graph = combine_graph(_model_graph, region_layers)
    return score_edge_ratio(_model_graph, relevant_regions=region_layers.keys())


class Score(object):
    def __init__(self, name, type, y, yerr, explanation):
        self.name = name
        self.type = type
        self.y = y
        self.yerr = yerr
        self.explanation = explanation

    def __repr__(self):
        return self.__class__.__name__ + "(" + ",".join(
            "{}={}".format(attr, val) for attr, val in self.__dict__.items()) + ")"


class Type(Enum):
    PHYSIOLOGY = auto
    ANATOMY = auto


class ScoreWorker(object):
    def __init__(self, activations_filepath, regions, model_name=None, map_all_layers=True):
        self._activations_filepath = activations_filepath
        self._regions = regions
        self._map_all_layers = map_all_layers
        self._model_name = model_name or model_name_from_activations_filepath(activations_filepath)

        [filepath, ext] = os.path.splitext(activations_filepath)
        storage_savepath = '{}-scores{}'.format(filepath, ext)
        self._cache = StorageCache(savepath=storage_savepath)

    def __call__(self, name, type):
        if (name, type) not in self._cache:
            if type == Type.PHYSIOLOGY:
                region_layer_mapping = physiology_mapping(self._activations_filepath, self._regions,
                                                          map_all_layers=self._map_all_layers)
                for region, (layers, score) in region_layer_mapping.items():
                    self._cache[(region, Type.PHYSIOLOGY)] = Score(
                        name=region, type=Type.PHYSIOLOGY, y=score, yerr=0, explanation=layers)
            elif type == Type.ANATOMY:
                region_layers = OrderedDict()
                for region in self._regions:
                    region_score = self(name=region, type=Type.PHYSIOLOGY)
                    layers = region_score.explanation
                    region_layers[region] = layers

                model = models.model_mappings[self._model_name](image_size=models._Defaults.image_size)[0]
                anatomy_score = score_anatomy(model, region_layers)
                self._cache[('edge_ratio', Type.ANATOMY)] = Score(
                    name='edge_ratio', type=Type.ANATOMY, y=anatomy_score, yerr=0, explanation=None)
            else:
                raise ValueError("Unknown type {}".format(type))
        return self._cache[(name, type)]


def score_model_activations(activations_filepath, regions, model_name=None, map_all_layers=True):
    scores = ScoreWorker(activations_filepath=activations_filepath, regions=regions, map_all_layers=map_all_layers,
                         model_name=model_name)
    physiology_scores = [scores(name=region, type=Type.PHYSIOLOGY) for region in regions]
    _logger.info("Physiology mapping: " + ", ".join("{} -> {} ({:.2f})".format(
        score.name, ",".join(score.explanation) if not isinstance(score.explanation, str) else score.explanation,
        score.y) for score in physiology_scores))
    return physiology_scores
    anatomy_score = scores(name='edge_ratio', type=Type.ANATOMY)
    _logger.info("Anatomy score: {}".format(anatomy_score))
    return physiology_scores + [anatomy_score]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activations_filepath', type=str, nargs='+',
                        default=[os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'images', 'sorted',
                                                              'vgg16-weights_imagenet-activations.pkl'))],
                        help='one or more filepaths to the model activations')
    parser.add_argument('--model', type=str, default=None, choices=models.model_mappings.keys(),
                        help='name of the model. Inferred from `--activations_filepath` if None')
    parser.add_argument('--regions', type=str, nargs='+', default=['V4', 'IT'], help='region(s) in brain to compare to')
    parser.add_argument('--map_all_layers', action='store_true', default=True)
    parser.add_argument('--no-map_all_layers', action='store_false', dest='map_all_layers')
    parser.add_argument('--log_level', type=str, default='INFO')
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stdout, level=logging.getLevelName(args.log_level))
    _logger.info("Running with args {}".format(vars(args)))

    for activations_filepath in args.activations_filepath:
        print(activations_filepath)
        scores = score_model_activations(activations_filepath, regions=args.regions, model_name=args.model,
                                         map_all_layers=args.map_all_layers)
        print(scores)


if __name__ == '__main__':
    main()