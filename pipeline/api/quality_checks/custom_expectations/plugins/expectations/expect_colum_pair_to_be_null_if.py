"""
This is a template for creating custom ColumnPairMapExpectations.
For detailed instructions on how to use it, please see:
    https://docs.greatexpectations.io/docs/guides/expectations/creating_custom_expectations/how_to_create_custom_column_pair_map_expectations
"""

from typing import Optional

from great_expectations.core import ExpectationConfiguration

from great_expectations.execution_engine import (
    PandasExecutionEngine,
)
from great_expectations.expectations.expectation import ColumnPairMapExpectation
from great_expectations.expectations.metrics.map_metric_provider import (
    ColumnPairMapMetricProvider,
    column_pair_condition_partial,
)

print("LOADED")

# This class defines a Metric to support your Expectation.
# For most ColumnPairMapExpectations, the main business logic for calculation will live in this class.


class ColumnPairValuesNullIf(ColumnPairMapMetricProvider):
    # This is the id string that will be used to reference your metric.
    condition_metric_name = "column_pair_values.null_if"
    # These point your metric at the provided keys to facilitate calculation
    condition_domain_keys = (
        "column_A",
        "column_B",
    )
    condition_value_keys = ("value_to_check",)

    # value_keys = ("value_to_check",)

    # This method implements the core logic for the PandasExecutionEngine
    @column_pair_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_A, column_B, value_to_check, **kwargs):
        # print(value_to_check)
        print("EEE")
        print("=" * 30)
        print(column_A)
        # print(column_A)
        # print(column_B)
        # # print(kwargs)
        # # print(abs(column_A - column_B) == 3)
        # # print(column_A.loc[(column_A == value_to_check) & (column_B == pd.NA)])
        # # print("MIAU")
        # # print((column_A == value_to_check) & (column_B == pd.NA))
        # print((column_A != value_to_check) | (column_A == value_to_check) & (column_B.isnull()))
        # print(column_B.isnull())
        return (column_A != value_to_check) | (column_A == value_to_check) & (
            column_B.isnull()
        )

    # This method defines the business logic for evaluating your metric when using a SqlAlchemyExecutionEngine
    # @column_pair_condition_partial(engine=SqlAlchemyExecutionEngine)F
    # def _sqlalchemy(cls, column_A, column_B, _dialect, **kwargs):
    #     raise NotImplementedError

    # This method defines the business logic for evaluating your metric when using a SparkDFExecutionEngine
    # @column_pair_condition_partial(engine=SparkDFExecutionEngine)
    # def _spark(cls, column_A, column_B, **kwargs):
    #     raise NotImplementedError


# This class defines the Expectation itself
class ExpectColumnPairToBeNullIf(ColumnPairMapExpectation):
    """Expect a column to be null if another column contains value."""

    # These examples will be shown in the public gallery.
    # They will also be executed as unit tests for your Expectation.
    examples = [
        {
            "data": {
                "col_a": [
                    3,
                    0,
                    1,
                ],
                "col_b": [
                    0,
                    -3,
                    4,
                ],
                "col_c": [
                    0,
                    None,
                    3,
                ],
            },
            "tests": [
                {
                    "title": "basic_positive_test",
                    "exact_match_out": False,
                    "include_in_gallery": True,
                    "in": {
                        "column_A": "col_a",
                        "column_B": "col_b",
                        "value_to_check": 5,
                    },
                    "out": {
                        "success": True,
                    },
                },
                {
                    "title": "basic_positive_test2",  # TODO: update
                    "exact_match_out": False,
                    "include_in_gallery": True,
                    "in": {
                        "column_A": "col_a",
                        "column_B": "col_c",
                        "value_to_check": 0,
                    },
                    "out": {
                        "success": True,
                    },
                },
                {
                    "title": "basic_negative_test",
                    "exact_match_out": False,
                    "include_in_gallery": True,
                    "in": {
                        "column_A": "col_a",
                        "column_B": "col_b",
                        "value_to_check": 0,
                    },
                    "out": {
                        "success": False,
                    },
                },
            ],
        }
    ]

    # This is the id string of the Metric used by this Expectation.
    # For most Expectations, it will be the same as the `condition_metric_name` defined in your Metric class above.
    map_metric = "column_pair_values.null_if"

    # This is a list of parameter names that can affect whether the Expectation evaluates to True or False
    success_keys = (
        "column_A",
        "column_B",
        "value_to_check",
    )

    def validate_configuration(
        self, configuration: Optional[ExpectationConfiguration]
    ) -> None:
        """
        Validates that a configuration has been set, and sets a configuration if it has yet to be set. Ensures that
        necessary configuration arguments have been provided for the validation of the expectation.

        Args:
            configuration (OPTIONAL[ExpectationConfiguration]): \
                An optional Expectation Configuration entry that will be used to configure the expectation
        Returns:
            None. Raises InvalidExpectationConfigurationError if the config is not validated successfully
        """

        super().validate_configuration(configuration)
        configuration = configuration or self.configuration

        # # Check other things in configuration.kwargs and raise Exceptions if needed
        # try:
        #     assert (
        #         ...
        #     ), "message"
        #     assert (
        #         ...
        #     ), "message"
        # except AssertionError as e:
        #     raise InvalidExpectationConfigurationError(str(e))

    # This object contains metadata for display in the public Gallery
    library_metadata = {
        "tags": [],  # Tags for this Expectation in the Gallery
        "contributors": [  # Github handles for all contributors to this Expectation.
            "@unai_zulaika",  # Don't forget to add your github handle here!
        ],
    }


if __name__ == "__main__":
    ExpectColumnPairToBeNullIf().print_diagnostic_checklist()
