from typing import List

import torchvision.transforms as T

from lib.engines import Engine
from lib.models import Model
from lib.models.jain_et_al import VGG
from lib.utils import Result
from lib.utils.mapping import Mapping
from lib.utils.transforms import RangeNormalize


class JainVggEngine(Engine):
    def provide_data_path(self) -> str:
        return "/mnt/nfs/work1/mfiterau/ADNI_data/jain_et_al"

    def provide_model(self) -> Model:
        return VGG()

    def provide_image_transforms(self) -> List[object]:
        return [
            T.ToTensor(),
            RangeNormalize()
        ]

    def run(self, *inputs, **kwargs) -> None:
        validation_folds = self.config.training_crossval_folds
        split_ratios = [1.0 / validation_folds] * validation_folds

        train_split, test_split = self.mapping.split_by_ratio([0.8, 0.2])
        results = []

        self.model = self.provide_model()
        parameters = list(self.model.parameters())
        parameters = [{"params": parameters[:-2], "lr": 0.0001}]
        self.optimizer = self.build_optimizer(parameters, optimizer_type="RMSprop")

        fold_train_split = train_split
        fold_valid_split = test_split

        self.train(num_epochs=self.config.train_epochs,
                   train_mapping=fold_train_split,
                   valid_mapping=fold_valid_split,
                   ith_fold=0)

        test_result = self.test(ith_fold=fold_idx, test_mapping=test_split)
        results.append(test_result)


    def train(self,
              num_epochs: int,
              ith_fold: int,
              train_mapping: Mapping,
              valid_mapping: Mapping) -> None:
        lowest_validation_loss = float("inf")

        for num_epoch in range(num_epochs):
            # ==========================================================================================================
            # Training
            # ==========================================================================================================
            self.logger.info(f"Starting training for epoch {num_epoch + 1}.")
            self.model.train()
            train_args = self.get_training_args(mapping=train_mapping)
            train_loop = super().loop_through_data_for_training(**train_args)
            train_result = Result(label_encoder=self.label_encoder)

            for iter_idx, (_, labels, loss, scores) in enumerate(train_loop):
                train_result.append_loss(loss)
                train_result.append_scores(scores, labels)

            self.logger.info(f"Finished training {num_epoch + 1} for {ith_fold + 1}th fold.")
            self.pretty_print_results(train_result, "train", f"{ith_fold + 1}th fold", num_epoch)

            # ==========================================================================================================
            # Validation
            # ==========================================================================================================
            self.logger.info(f"Starting validation for epoch {num_epoch + 1}.")
            self.model.eval()
            valid_args = self.get_testing_args(mapping=valid_mapping)
            valid_result = super().loop_through_data_for_testing(**valid_args)

            self.logger.info(f"Finished validation {num_epoch + 1} for {ith_fold + 1}th fold.")
            self.pretty_print_results(valid_result, "validate", f"{ith_fold + 1}th fold", num_epoch)

            validation_loss = valid_result.calculate_mean_loss()

            if lowest_validation_loss > validation_loss and self.config.save_best_model:
                self.logger.info(f"{lowest_validation_loss} > {validation_loss}, saving model...")
                self.save_current_model(file_name="lowest_loss.pt")


    def test(self, ith_fold: int, test_mapping: Mapping) -> Result:
        self.logger.info(f"Starting test for {ith_fold + 1}th fold.")
        self.model = self.provide_model()
        Engine.initialize_model(self.model, from_path=f"{self.model_output_folder}/lowest_loss.pt")
        self.model.eval()

        test_args = self.get_testing_args(mapping=test_mapping)
        test_result = super().loop_through_data_for_testing(**test_args)

        self.logger.info(f"Finished testing for fold {ith_fold + 1}")
        self.pretty_print_results(test_result, "test", f"{ith_fold + 1}th fold", 0)

        result_path = f"{self.result_output_folder}/{ith_fold}th_fold_results.dict"
        self.logger.info(f"Saving results for {ith_fold + 1}th fold validation to {result_path}...")
        test_result.save_state(file_path=result_path)
        return test_result
