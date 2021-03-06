from typing import List

import torchvision.transforms as T

from lib.engines import Engine
from lib.models import Model
from lib.models.wang_et_al import DenseNet
from lib.utils import Result
from lib.utils.mapping import Mapping
from lib.utils.transforms import RangeNormalize


class WangDenseNetEngine(Engine):
    def provide_data_path(self) -> str:
        return "/mnt/nfs/work1/mfiterau/ADNI_data/wang_et_al"

    def provide_model(self) -> Model:
        return DenseNet()

    def provide_image_transforms(self) -> List[object]:
        return [
            T.ToTensor(),
            RangeNormalize()
        ]

    def run(self, *inputs, **kwargs) -> None:
        validation_folds = self.config.training_crossval_folds
        split_ratios = [1.0 / validation_folds] * validation_folds

        train_split = self.mapping
        results = []

        for fold_idx in range(validation_folds):
            self.logger.info(f"Running {fold_idx + 1}th fold.")
            self.model = self.provide_model()
            parameters = list(self.model.parameters())
            parameters = [{"params": parameters, "lr": 0.01}]
            self.optimizer = self.build_optimizer(parameters, optimizer_type="sgd", momentum=self.config.train_momentum)
            
            copied_splits: List[Mapping] = train_split.split_by_ratio(split_ratios)
            fold_valid_split = copied_splits.pop(fold_idx)
            fold_train_split = Mapping.merge(copied_splits)
            
            valid_result = self.train(num_epochs=self.config.train_epochs,
                       train_mapping=fold_train_split,
                       valid_mapping=fold_valid_split,
                       ith_fold=fold_idx)

            results.append(valid_result)


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
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = 0.01 * (1-float(num_epochs*train_mapping.__len__()/10 + iter_idx)/1000)**0.005
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
            
            
            if num_epochs * train_mapping.__len__() / 10 > 1000:
                return valid_result

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
