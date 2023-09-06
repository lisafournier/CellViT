# -*- coding: utf-8 -*-
# CellVit Experiment Class
#
# @ Fabian Hörst, fabian.hoerst@uk-essen.de
# Institute for Artifical Intelligence in Medicine,
# University Medicine Essen

import inspect
import os
import sys

import yaml

from base_ml.base_trainer import BaseTrainer

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

from pathlib import Path
from typing import Callable, Tuple, Union

import torch
import torch.nn as nn
from torch.optim import Optimizer
from torch.optim.lr_scheduler import (
    ConstantLR,
    CosineAnnealingLR,
    ExponentialLR,
    ReduceLROnPlateau,
    SequentialLR,
    _LRScheduler,
)
from torch.utils.data import Dataset
from torchinfo import summary

from base_ml.base_loss import retrieve_loss_fn
from cell_segmentation.experiments.experiment_cellvit import ExperimentCellViT
from cell_segmentation.trainer.trainer_stardist import CellViTStarDistTrainer
from models.segmentation.cell_segmentation.cellvit import (
    CellViT256StarDist,
    CellViTSAMStarDist,
    CellViTStarDist,
)


class ExperimentCellViTStarDist(ExperimentCellViT):
    def load_dataset_setup(self, dataset_path: Union[Path, str]) -> None:
        """Load the configuration of the cell segmentation dataset.

        The dataset must have a dataset_config.yaml file in their dataset path with the following entries:
            * tissue_types: describing the present tissue types with corresponding integer
            * nuclei_types: describing the present nuclei types with corresponding integer

        Args:
            dataset_path (Union[Path, str]): Path to dataset folder
        """
        dataset_config_path = Path(dataset_path) / "dataset_config.yaml"
        with open(dataset_config_path, "r") as dataset_config_file:
            yaml_config = yaml.safe_load(dataset_config_file)
            self.dataset_config = dict(yaml_config)

    def get_loss_fn(self, loss_fn_settings: dict) -> dict:
        """Create a dictionary with loss functions for all branches

        Branches: "stardist_map", "dist_map", "nuclei_type_map", "tissue_types"

        Args:
            loss_fn_settings (dict): Dictionary with the loss function settings. Structure
            branch_name(str):
                loss_name(str):
                    loss_fn(str): String matching to the loss functions defined in the LOSS_DICT (base_ml.base_loss)
                    weight(float): Weighting factor as float value
                    (optional) args:  Optional parameters for initializing the loss function
                            arg_name: value

            If a branch is not provided, the defaults settings (described below) are used.

            For further information, please have a look at the file configs/examples/cell_segmentation/train_cellvit.yaml
            under the section "loss"

            Example:
                  nuclei_binary_map:
                    bce:
                        loss_fn: xentropy_loss
                        weight: 1
                    dice:
                        loss_fn: dice_loss
                        weight: 1

        Returns:
            dict: Dictionary with loss functions for each branch. Structure:
                branch_name(str):
                    loss_name(str):
                        "loss_fn": Callable loss function
                        "weight": weight of the loss since in the end all losses of all branches are added together for backward pass
                    loss_name(str):
                        "loss_fn": Callable loss function
                        "weight": weight of the loss since in the end all losses of all branches are added together for backward pass
                branch_name(str)
                ...

        Default loss dictionary:
            nuclei_binary_map:
                bce:
                    loss_fn: xentropy_loss
                    weight: 1
                dice:
                    loss_fn: dice_loss
                    weight: 1
            hv_map:
                mse:
                    loss_fn: mse_loss_maps
                    weight: 1
                msge:
                    loss_fn: msge_loss_maps
                    weight: 1
            nuclei_type_map
                bce:
                    loss_fn: xentropy_loss
                    weight: 1
                dice:
                    loss_fn: dice_loss
                    weight: 1
            tissue_types
                ce:
                    loss_fn: nn.CrossEntropyLoss()
                    weight: 1
        """
        loss_fn_dict = {}
        if "stardist_map" in loss_fn_settings.keys():
            loss_fn_dict["stardist_map"] = {}
            for loss_name, loss_sett in loss_fn_settings["stardist_map"].items():
                parameters = loss_sett.get("args", {})
                loss_fn_dict["stardist_map"][loss_name] = {
                    "loss_fn": retrieve_loss_fn(loss_sett["loss_fn"], **parameters),
                    "weight": loss_sett["weight"],
                }
        else:
            loss_fn_dict["stardist_map"] = {
                "mae": {
                    "loss_fn": retrieve_loss_fn(
                        "MAEWeighted", alpha=0.0001, apply_mask=True
                    ),
                    "weight": 0.2,
                },
            }
        if "dist_map" in loss_fn_settings.keys():
            loss_fn_dict["dist_map"] = {}
            for loss_name, loss_sett in loss_fn_settings["dist_map"].items():
                parameters = loss_sett.get("args", {})
                loss_fn_dict["dist_map"][loss_name] = {
                    "loss_fn": retrieve_loss_fn(loss_sett["loss_fn"], **parameters),
                    "weight": loss_sett["weight"],
                }
        else:
            loss_fn_dict["dist_map"] = {
                "bce": {
                    "loss_fn": retrieve_loss_fn("BCEWeighted", apply_mask=True),
                    "weight": 1,
                },
                "mse": {"loss_fn": retrieve_loss_fn("MSEWeighted"), "weight": 1},
            }
        if "nuclei_type_map" in loss_fn_settings.keys():
            loss_fn_dict["nuclei_type_map"] = {}
            for loss_name, loss_sett in loss_fn_settings["nuclei_type_map"].items():
                parameters = loss_sett.get("args", {})
                loss_fn_dict["nuclei_type_map"][loss_name] = {
                    "loss_fn": retrieve_loss_fn(loss_sett["loss_fn"], **parameters),
                    "weight": loss_sett["weight"],
                }
        else:
            loss_fn_dict["nuclei_type_map"] = {
                "bce": {"loss_fn": retrieve_loss_fn("xentropy_loss"), "weight": 1},
                "dice": {"loss_fn": retrieve_loss_fn("dice_loss"), "weight": 1},
            }
        if "tissue_types" in loss_fn_settings.keys():
            loss_fn_dict["tissue_types"] = {}
            for loss_name, loss_sett in loss_fn_settings["tissue_types"].items():
                parameters = loss_sett.get("args", {})
                loss_fn_dict["tissue_types"][loss_name] = {
                    "loss_fn": retrieve_loss_fn(loss_sett["loss_fn"], **parameters),
                    "weight": loss_sett["weight"],
                }
        else:
            loss_fn_dict["tissue_types"] = {
                "ce": {"loss_fn": nn.CrossEntropyLoss(), "weight": 1},
            }
        return loss_fn_dict

    def get_scheduler(self, scheduler_type: str, optimizer: Optimizer) -> _LRScheduler:
        """Get the learning rate scheduler for CellViT

        The configuration of the scheduler is given in the "training" -> "scheduler" section.
        Currenlty, "constant", "exponential" and "cosine" schedulers are implemented.

        Required parameters for implemented schedulers:
            - "constant": None
            - "exponential": gamma (optional, defaults to 0.95)
            - "cosine": eta_min (optional, defaults to 1-e5)

        Args:
            scheduler_type (str): Type of scheduler as a string. Currently implemented:
                - "constant" (lowering by a factor of ten after 25 epochs, increasing after 50, decreasimg again after 75)
                - "exponential" (ExponentialLR with given gamma, gamma defaults to 0.95)
                - "cosine" (CosineAnnealingLR, eta_min as parameter, defaults to 1-e5)
            optimizer (Optimizer): Optimizer

        Returns:
            _LRScheduler: PyTorch Scheduler
        """
        implemented_schedulers = ["constant", "exponential", "cosine"]
        if scheduler_type.lower() not in implemented_schedulers:
            self.logger.warning(
                f"Unknown Scheduler - No scheduler from the list {implemented_schedulers} select. Using default scheduling."
            )
        if scheduler_type.lower() == "constant":
            scheduler = SequentialLR(
                optimizer=optimizer,
                schedulers=[
                    ConstantLR(optimizer, factor=1, total_iters=25),
                    ConstantLR(optimizer, factor=0.1, total_iters=25),
                    ConstantLR(optimizer, factor=1, total_iters=25),
                    ConstantLR(optimizer, factor=0.1, total_iters=1000),
                ],
                milestones=[24, 49, 74],
            )
        elif scheduler_type.lower() == "exponential":
            scheduler = ExponentialLR(
                optimizer,
                gamma=self.run_conf["training"]["scheduler"].get("gamma", 0.95),
            )
        elif scheduler_type.lower() == "cosine":
            scheduler = CosineAnnealingLR(
                optimizer,
                T_max=self.run_conf["training"]["epochs"],
                eta_min=self.run_conf["training"]["scheduler"].get("eta_min", 1e-5),
            )
        elif scheduler_type.lower() == "reducelronplateau":
            scheduler = ReduceLROnPlateau(
                mode="min",
            )
        else:
            scheduler = super().get_scheduler(optimizer)
        return scheduler

    def get_datasets(
        self,
        dataset_name: str,
        train_transforms: Callable = None,
        val_transforms: Callable = None,
    ) -> Tuple[Dataset, Dataset]:
        """Retrieve training dataset and validation dataset

        Args:
            dataset_name (str): Name of dataset to use
            train_transforms (Callable, optional): PyTorch transformations for train set. Defaults to None.
            val_transforms (Callable, optional): PyTorch transformations for validation set. Defaults to None.

        Returns:
            Tuple[Dataset, Dataset]: Training dataset and validation dataset
        """
        self.run_conf["data"]["stardist"] = True
        train_dataset, val_dataset = super().get_datasets(
            dataset_name=dataset_name,
            train_transforms=train_transforms,
            val_transforms=val_transforms,
        )
        return train_dataset, val_dataset

    def get_train_model(
        self,
        pretrained_encoder: Union[Path, str] = None,
        pretrained_model: Union[Path, str] = None,
        backbone_type: str = "default",
        **kwargs,
    ) -> CellViTStarDist:
        """Return the CellViTStarDist training model

        Args:
            pretrained_encoder (Union[Path, str]): Path to a pretrained encoder. Defaults to None.
            pretrained_model (Union[Path, str], optional): Path to a pretrained model. Defaults to None.
            backbone_type (str, optional): Backbone Type. Currently supported are default (None, ViT256, SAM-B, SAM-L, SAM-H). Defaults to None
            **kwargs for downward compatibilitys
        Returns:
            CellViTStarDist: CellViTStarDist training model with given setup
        """
        torch.manual_seed(0)
        implemented_backbones = ["default", "ViT256", "SAM-B", "SAM-L", "SAM-H"]

        if backbone_type not in implemented_backbones:
            raise NotImplementedError(
                f"Unknown Backbone Type - Currently supported are: {implemented_backbones}"
            )
        if backbone_type.lower() == "default":
            model_class = CellViTStarDist
            model = model_class(
                num_nuclei_classes=self.run_conf["data"]["num_nuclei_classes"],
                num_tissue_classes=self.run_conf["data"]["num_tissue_classes"],
                embed_dim=self.run_conf["model"]["embed_dim"],
                input_channels=self.run_conf["model"].get("input_channels", 3),
                depth=self.run_conf["model"]["depth"],
                num_heads=self.run_conf["model"]["num_heads"],
                extract_layers=self.run_conf["model"]["extract_layers"],
                drop_rate=self.run_conf["training"].get("drop_rate", 0),
                attn_drop_rate=self.run_conf["training"].get("attn_drop_rate", 0),
                drop_path_rate=self.run_conf["training"].get("drop_path_rate", 0),
                nrays=self.run_conf["model"].get("nrays", 32),
            )

            if pretrained_model is not None:
                self.logger.info(
                    f"Loading pretrained CellViT model from path: {pretrained_model}"
                )
                cellvit_pretrained = torch.load(pretrained_model)
                self.logger.info(model.load_state_dict(cellvit_pretrained, strict=True))
                self.logger.info("Loaded CellViT model")

        if backbone_type == "ViT256":
            model_class = CellViT256StarDist
            model = model_class(
                model256_path=pretrained_encoder,
                num_nuclei_classes=self.run_conf["data"]["num_nuclei_classes"],
                num_tissue_classes=self.run_conf["data"]["num_tissue_classes"],
                drop_rate=self.run_conf["training"].get("drop_rate", 0),
                attn_drop_rate=self.run_conf["training"].get("attn_drop_rate", 0),
                drop_path_rate=self.run_conf["training"].get("drop_path_rate", 0),
                nrays=self.run_conf["model"].get("nrays", 32),
            )
            model.load_pretrained_encoder(model.model256_path)
            if pretrained_model is not None:
                self.logger.info(
                    f"Loading pretrained CellViT model from path: {pretrained_model}"
                )
                cellvit_pretrained = torch.load(pretrained_model, map_location="cpu")
                self.logger.info(model.load_state_dict(cellvit_pretrained, strict=True))
            model.freeze_encoder()
            self.logger.info("Loaded CellVit256 model")
        if backbone_type in ["SAM-B", "SAM-L", "SAM-H"]:
            model_class = CellViTSAMStarDist
            model = model_class(
                model_path=pretrained_encoder,
                num_nuclei_classes=self.run_conf["data"]["num_nuclei_classes"],
                num_tissue_classes=self.run_conf["data"]["num_tissue_classes"],
                vit_structure=backbone_type,
                drop_rate=self.run_conf["training"].get("drop_rate", 0),
                nrays=self.run_conf["model"].get("nrays", 32),
            )
            model.load_pretrained_encoder(model.model_path)
            if pretrained_model is not None:
                self.logger.info(
                    f"Loading pretrained CellViT model from path: {pretrained_model}"
                )
                cellvit_pretrained = torch.load(pretrained_model, map_location="cpu")
                self.logger.info(model.load_state_dict(cellvit_pretrained, strict=True))
            model.freeze_encoder()
            self.logger.info(f"Loaded CellViT-SAM model with backbone: {backbone_type}")

        self.logger.info(f"\nModel: {model}")
        model = model.to("cpu")
        self.logger.info(
            f"\n{summary(model, input_size=(1, 3, 256, 256), device='cpu')}"
        )

        return model

    def get_trainer(self) -> BaseTrainer:
        """Return Trainer matching to this network

        Returns:
            BaseTrainer: Trainer
        """
        return CellViTStarDistTrainer
