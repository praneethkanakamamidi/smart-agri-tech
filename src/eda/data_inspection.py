from abc import ABC, abstractmethod
import pandas as pd


class InspectingDataStrategy(ABC):
    """
    Abstract base class that defines the interface for data inspection strategies.

    Subclasses must implement the 'inspect' method to provide a specific inspection logic
    for data analysis.
    """
    @abstractmethod
    def inspect(self, df: pd.DataFrame):
        """
        Perform inspection on the given DataFrame.

        Args:
            df (pd.DataFrame): The pandas DataFrame containing the data to inspect.
        
        Raises:
            NotImplementedError: If the method is not implemented by subclasses.
        """
        pass


class InspectingDatatypesStrategy(InspectingDataStrategy):
    """
    Concrete strategy for inspecting the data types and non-null counts in a DataFrame.

    This class provides an implementation of the 'inspect' method that prints the data types 
    and non-null counts for each column in the DataFrame.
    """
    def inspect(self, df: pd.DataFrame):
        """
        Inspect the data types and non-null counts of the given DataFrame.

        Args:
            df (pd.DataFrame): The pandas DataFrame to analyze.
        """
        print("\nCount of data types and non-null elements:")
        print(df.info())


class InspectingSummaryStatistics(InspectingDataStrategy):
    """
    Concrete strategy for inspecting the summary statistics of numerical and categorical features
    in a DataFrame.

    This class provides an implementation of the 'inspect' method that prints summary statistics 
    for numerical features and categorical features (if any).
    """
    def inspect(self, df: pd.DataFrame):
        """
        Inspect and print the summary statistics of numerical and categorical features.

        Args:
            df (pd.DataFrame): The pandas DataFrame to analyze.
        """
        print("\nStatistical Summary of numerical features:")
        print(df.describe())
        print("\nCategorical Summary of features:")
        print(df.describe(include=["O"]))


class DataInspector:
    """
    The DataInspector class is responsible for managing different inspection strategies and executing them.

    This class allows setting and executing different inspection strategies on a DataFrame.
    """
    def __init__(self, strategy: InspectingDataStrategy):
        """
        Initialize the DataInspector with a specific inspection strategy.

        Args:
            strategy (InspectingDataStrategy): The strategy to use for inspecting the data.
        """
        self._strategy = strategy

    def configure_strategy(self, strategy: InspectingDataStrategy):
        """
        Configure the current inspection strategy.

        Args:
            strategy (InspectingDataStrategy): The new strategy to set for data inspection.
        """
        self._strategy = strategy

    def run_inspection(self, df: pd.DataFrame):
        """
        Run the configured inspection strategy on the provided DataFrame.

        Args:
            df (pd.DataFrame): The pandas DataFrame to inspect using the current strategy.
        """
        self._strategy.inspect(df)
