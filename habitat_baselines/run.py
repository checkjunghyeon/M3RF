#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import os
import sys

sys.path.insert(0, "")
import argparse
import random
import numpy as np
from habitat_baselines.common.baseline_registry import baseline_registry
from habitat_baselines.config.default import get_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-type",
        choices=["train", "eval"],
        required=True,
        help="run type of the experiment (train or eval)",
    )
    parser.add_argument(
        "--exp-config",
        type=str,
        required=True,
        help="path to config yaml containing info about experiment",
    )

    parser.add_argument(
        "--agent-type",
        choices=["no-map", "oracle", "oracle-ego", "proj-neural", "obj-recog", "semseg"],
        required=True,
        help="agent type: oracle, oracleego, projneural, objrecog, semseg",
    )

    parser.add_argument(
        "opts",
        default=None,
        nargs=argparse.REMAINDER,
        help="Modify config options from command line",
    )

    # Auxiliary losses coefficients
    parser.add_argument(
        "--seen_coef",
        type=float,
        default=0,
        help="Aux loss seen coef",
    )
    parser.add_argument(
        "--dir_coef",
        type=float,
        default=0,
        help="Aux loss direction coef",
    )
    parser.add_argument(
        "--dist_coef",
        type=float,
        default=0,
        help="Aux loss distance coef",
    )

    # grounding - step1
    # ours: GroundingDINO
    # ablation 1: Faster R-CNN
    parser.add_argument(
        "--goal_grounder",
        choices=["GroundingDINO", "FasterRCNN", "GoalMasking"],
        required=True,
        help="Goal object detector",
    )

    # Eval params (path to ckpt and eval split)
    parser.add_argument(
        "--eval_path",
        type=str,
        help="path to eval cpt folder",
    )
    parser.add_argument(
        "--eval_split",
        type=str,
        help="data split to evaluate the model on",
    )
    parser.add_argument(
        "--continue-training",
        type=str,
        default=None,
        help="continue training based on given model",
    )

    parser.add_argument(
        '--with_img_segm',
        dest='with_img_segm',
        default=True,
        action='store_false',
        help='uses the img segmentation pre-trained model during training or testing'
    )
    args = parser.parse_args()
    run_exp(**vars(args))


def run_exp(
    exp_config: str,
    run_type: str,
    agent_type: str,
    seen_coef: int,
    dir_coef: int,
    dist_coef: int,
    goal_grounder: str, # grounding - step2
    eval_path: str,
    eval_split: str,
    opts=None,
    continue_training=None,
    with_img_segm=None
) -> None:
    r"""Runs experiment given mode and config

    Args:
        exp_config: path to config file.
        run_type: "train" or "eval.
        opts: list of strings of additional config options.

    Returns:
        None.
    """
    config = get_config(exp_config, opts)
    random.seed(config.TASK_CONFIG.SEED)
    np.random.seed(config.TASK_CONFIG.SEED)

    config.defrost()
    config.TRAINER_NAME = agent_type
    config.TASK_CONFIG.TRAINER_NAME = agent_type
    config.CONTINUE_TRAINING = continue_training
    config.WITH_IMG_SEGM = with_img_segm
    config.DETECTOR_TYPE = goal_grounder  # grounding - step3

    compute_oracle_supervision = False
    if seen_coef > 0:
        config.RL.PPO.aux_loss_seen_coef = seen_coef
        compute_oracle_supervision = True
    else:
        config.RL.PPO.aux_loss_seen_coef = None

    if dir_coef > 0:
        config.RL.PPO.aux_loss_direction_coef = dir_coef
        compute_oracle_supervision = True
    else:
        config.RL.PPO.aux_loss_direction_coef = None

    if dist_coef > 0:
        config.RL.PPO.aux_loss_distance_coef = dist_coef
        compute_oracle_supervision = True
    else:
        config.RL.PPO.aux_loss_distance_coef = None
    config.TASK_CONFIG.COMPUTE_ORACLE_SUPERVISION = compute_oracle_supervision

    if run_type == "eval":
        config.EVAL_CKPT_PATH_DIR = eval_path
        assert eval_split in ["val", "test"]
        config.TASK_CONFIG.DATASET.SPLIT = eval_split
        config.EVAL.SPLIT = eval_split

        if eval_split == "val":
            assert (
                config.NUM_PROCESSES <= 11
            ), "Val set contains episodes from 11 scenes. You should not have more processes than scenes."
        elif eval_split == "test":
            assert (
                config.NUM_PROCESSES <= 18
            ), "Test set contains episodes from 18 scenes. You should not have more processes than scenes."

    config.freeze()

    if agent_type in ["oracle", "oracle-ego", "no-map"]:
        trainer_init = baseline_registry.get_trainer("oracle")
        config.defrost()
        config.RL.PPO.hidden_size = 512 if agent_type == "no-map" else 768
        config.TASK_CONFIG.SIMULATOR.DEPTH_SENSOR.MIN_DEPTH = 0.5
        config.TASK_CONFIG.SIMULATOR.DEPTH_SENSOR.MAX_DEPTH = 5.0
        config.TASK_CONFIG.SIMULATOR.AGENT_0.HEIGHT = 1.5

        if agent_type == "oracle-ego" or (
            agent_type == "no-map" and compute_oracle_supervision
        ):
            config.TASK_CONFIG.TASK.MEASUREMENTS.append("FOW_MAP")
        config.freeze()
    elif agent_type in ["semseg"]:
        trainer_init = baseline_registry.get_trainer("non-oracle")
        config.defrost()
        config.RL.PPO.hidden_size = 512
        config.TASK_CONFIG.TASK.MEASUREMENTS.append('FOW_MAP')
        config.freeze()
    else:
        trainer_init = baseline_registry.get_trainer("non-oracle")
        config.defrost()
        config.RL.PPO.hidden_size = 512

        if compute_oracle_supervision:
            config.TASK_CONFIG.TASK.MEASUREMENTS.append("FOW_MAP")
        config.freeze()

    assert trainer_init is not None, f"{config.TRAINER_NAME} is not supported"
    trainer = trainer_init(config)

    if run_type == "train":
        trainer.train()
    elif run_type == "eval":
        trainer.eval()


if __name__ == "__main__":
    main()
